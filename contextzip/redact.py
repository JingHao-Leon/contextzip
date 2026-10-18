"""
redact.py — Best-effort in-content secret redaction.

Implements the `limits.redact_secrets` project setting (see project_config.py),
which until now was persisted and editable in the config UI but never actually
enforced by the packaging logic — see the 0.4.0 changelog's "known
limitation."

This is deliberately a *second line of defense*, not a replacement for the
secrets/credentials exclusion list (rules/base.py's SECRET_PATTERNS). That
list keeps whole files that are almost certainly secrets (private keys,
credential files, .env) out of the archive by default. This module instead
handles the narrower case those file-level rules can't catch: an ordinary
source or config file that's fine to include, but happens to have a
secret-shaped value hardcoded somewhere inside it (e.g. an AWS key pasted
into a settings.py for local testing).

Secret files the user deliberately includes
───────────────────────────────────────────
A project's `always_include` can bring a SECRET_PATTERNS file back on
purpose — most often a `.env`, so the AI tool can see which variables the
app expects. Those files are never written as-is (see redact_sensitive_file,
called unconditionally by packager.py, whatever `limits.redact_secrets`
says):
  - `.env` / `.env.*` files keep every key, comment and blank line, but
    every value becomes "[REDACTED]" — not just the secret-shaped ones,
    because a dotenv value is a secret far too often to guess which aren't.
  - Any other secret file gets the same pattern scan as above.
  - A secret file that isn't UTF-8 text (a .p12, a .jks keystore) can't be
    redacted, so packager.py skips it instead of zipping it raw.

Design choices, deliberately conservative to match the rest of the project:
  - A curated list of high-precision patterns (known key/token formats,
    private-key blocks, JWTs, and a narrow generic key=value assignment
    form) rather than an entropy-based scan — same "curated list, not a
    heuristic" approach as the file-level secrets baseline in packager.py.
  - Only the matched *value* is replaced with "[REDACTED...]", not the
    whole line — a redacted file should stay useful context for whatever
    AI tool receives the archive.
  - Obvious placeholders ("changeme", "xxxxxxxx", "<your-key-here>") are
    left alone rather than redacted, so example/template files don't get
    needlessly mangled.

Performance: the opt-in scan only ever runs on files the caller has already
confirmed are text and within `limits.max_file_size_mb` (see packager.py,
which reuses the binary/large-file classification `resolve_files()` already
computes) — never on binaries or oversized files. Deliberately included
secret files are the one exception: they're always scanned, whatever their
size. A handful of compiled regexes over a
small text file costs low-single-digit milliseconds; across an entire
project it's negligible next to the I/O of zipping in the first place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

import pathspec

from contextzip.rules.base import SECRET_PATTERNS

REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class _SecretPattern:
    name: str
    regex: re.Pattern[str]
    # Which regex group holds the actual secret value to redact.
    # 0 means "redact the whole match" (used for freestanding key formats
    # with no surrounding key=value context to preserve).
    value_group: int = 0


_PLACEHOLDER_VALUES = {
    "changeme",
    "change_me",
    "your_api_key_here",
    "your-api-key-here",
    "your_key_here",
    "example",
    "placeholder",
    "insert_key_here",
    "todo",
    "fixme",
    "xxx",
    "n/a",
    "none",
    "null",
    "test",
    "fake",
    "dummy",
}


def _looks_like_placeholder(value: str) -> bool:
    v = value.strip().strip("'\"").lower()
    if not v:
        return True
    if v in _PLACEHOLDER_VALUES:
        return True
    if set(v) <= {"x"}:  # xxxxxxxx, XXXXXXXX
        return True
    if v.startswith("<") and v.endswith(">"):  # <your-key-here>
        return True
    if v.startswith("$") or v.startswith("{{") or v.startswith("%"):
        # env-var interpolation / templating placeholders, e.g. ${API_KEY},
        # {{ secrets.API_KEY }}, %API_KEY% — a reference, not a live secret.
        return True
    return False


# Freestanding, self-identifying formats — redact the whole match, no
# surrounding key=value context needed.
_PATTERNS: list[_SecretPattern] = [
    _SecretPattern("AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    _SecretPattern("Google API Key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    _SecretPattern("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    _SecretPattern("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,48}\b")),
    _SecretPattern("Stripe Key", re.compile(r"\bsk_(?:live|test)_[0-9A-Za-z]{24,}\b")),
    _SecretPattern("Anthropic API Key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b")),
    _SecretPattern("OpenAI API Key", re.compile(r"\bsk-proj-[A-Za-z0-9\-_]{20,}\b")),
    _SecretPattern(
        "JWT",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    _SecretPattern(
        "Private Key Block",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
            r"[\s\S]+?"
            r"-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
        ),
    ),
    # AWS secret access keys have no distinguishing prefix, so this one
    # needs the "aws_secret_access_key = ..." context to be high-precision.
    _SecretPattern(
        "AWS Secret Access Key",
        re.compile(
            r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"
        ),
        value_group=1,
    ),
    # Narrow generic assignment: fires when a key/secret/token/password-shaped
    # word appears in the assigned name (standalone or as part of a
    # compound identifier like DB_PASSWORD, STRIPE_SECRET_KEY), assigned a
    # quoted value of at least 10 chars — conservative on purpose to keep
    # false positives low, though a false positive here only means an
    # unnecessary "[REDACTED]" in the zip copy, not any change to the
    # user's actual file.
    _SecretPattern(
        "Generic Secret Assignment",
        re.compile(
            r"(?i)\b[A-Za-z0-9_]*?"
            r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|"
            r"auth[_-]?token|client[_-]?secret|password|passwd)"
            r"[A-Za-z0-9_]*\s*[:=]\s*['\"]([^'\"\s]{10,})['\"]"
        ),
        value_group=1,
    ),
]


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """
    Scan *text* for secret-shaped values and replace each one with
    "[REDACTED]", leaving everything else — including the surrounding
    key name, quotes, and punctuation — untouched.

    Returns (possibly-modified text, list of pattern names that matched at
    least once — e.g. ["AWS Access Key ID", "Generic Secret Assignment"]).
    An empty list means nothing matched and *text* is returned unchanged
    (the same string object, so callers can cheaply check `if matched:`
    to skip rewriting a file that didn't need it).
    """
    matched_names: list[str] = []

    for pattern in _PATTERNS:

        def _sub(m: re.Match[str], pattern: _SecretPattern = pattern) -> str:
            value = m.group(pattern.value_group)
            if _looks_like_placeholder(value):
                return m.group(0)
            matched_names.append(pattern.name)
            if pattern.value_group == 0:
                return "[REDACTED]"
            full = m.group(0)
            g_start, g_end = m.span(pattern.value_group)
            rel_start = g_start - m.start()
            rel_end = g_end - m.start()
            return full[:rel_start] + "[REDACTED]" + full[rel_end:]

        text = pattern.regex.sub(_sub, text)

    return text, matched_names


# ---------------------------------------------------------------------------
# Secret files the user deliberately included (see module docstring)
# ---------------------------------------------------------------------------

_SECRET_SPEC = pathspec.PathSpec.from_lines("gitwildmatch", SECRET_PATTERNS)

# KEY=value, optionally prefixed with `export` — the dotenv assignment form.
_ENV_ASSIGNMENT = re.compile(r"^(\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_.\-]*\s*=[ \t]*)(.*)$")

ENV_VALUE = ".env value"


def is_sensitive_path(rel: PurePath | str) -> bool:
    """True if *rel* (relative to the project root) matches SECRET_PATTERNS."""
    rel_str = PurePath(rel).as_posix()
    if _SECRET_SPEC.match_file(rel_str):
        return True
    parts = PurePath(rel_str).parts[:-1]
    return any(
        _SECRET_SPEC.match_file("/".join(parts[: i + 1]) + "/") for i in range(len(parts))
    )


def is_env_file(rel: PurePath | str) -> bool:
    """True for `.env` and `.env.*` files (`.env.local`, `.env.production`, ...)."""
    name = PurePath(rel).name
    return name == ".env" or name.startswith(".env.")


def _split_line_ending(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body):]


def _closing_quote(value: str, quote: str, start: int) -> int:
    """Index of the closing *quote* in *value* at or after *start*, or -1."""
    i = start
    while i < len(value):
        if value[i] == "\\" and quote == '"':
            i += 2
            continue
        if value[i] == quote:
            return i
        i += 1
    return -1


def _safe_tail(tail: str) -> str:
    """Keep what follows a closing quote only if it's blank or a `#comment`."""
    if not tail.strip() or re.match(r"\s+#", tail):
        return tail
    return " " + REDACTED


def redact_env(text: str) -> tuple[str, int]:
    """
    Replace every value in a dotenv file with "[REDACTED]".

    Keys, `export` prefixes, quotes, inline comments, blank lines and line
    endings are kept, so the file still tells the reader which variables
    exist. Quoted values that span several lines collapse to one redacted
    line. Any other non-comment line (something that isn't KEY=value) is
    redacted whole, since it might be a pasted secret.

    Returns (redacted text, number of values redacted).
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    count = 0
    i = 0

    while i < len(lines):
        body, ending = _split_line_ending(lines[i])
        i += 1
        stripped = body.strip()

        if not stripped or stripped.startswith("#"):
            out.append(body + ending)
            continue

        m = _ENV_ASSIGNMENT.match(body)
        if not m:
            out.append(REDACTED + ending)
            count += 1
            continue

        prefix, value = m.group(1), m.group(2)
        if not value.strip():
            out.append(body + ending)
            continue

        count += 1
        quote = value[0]
        if quote not in "\"'`":
            # Unquoted: the value runs up to an inline ` #comment`.
            comment = re.search(r"\s+#.*$", value)
            tail = comment.group(0) if comment else ""
            out.append(prefix + REDACTED + tail + ending)
            continue

        close = _closing_quote(value, quote, 1)
        if close != -1:
            out.append(prefix + quote + REDACTED + quote + _safe_tail(value[close + 1:]) + ending)
            continue

        # Multi-line quoted value: swallow lines until the closing quote.
        tail = None
        while i < len(lines):
            next_body, ending = _split_line_ending(lines[i])
            i += 1
            close = _closing_quote(next_body, quote, 0)
            if close != -1:
                tail = next_body[close + 1:]
                break
        if tail is None:
            # Never closed — everything after the opening quote is the value.
            out.append(prefix + REDACTED + ending)
        else:
            out.append(prefix + quote + REDACTED + quote + _safe_tail(tail) + ending)

    return "".join(out), count


def redact_sensitive_file(rel: PurePath | str, text: str) -> tuple[str, list[str]]:
    """
    Redact a SECRET_PATTERNS file the user deliberately included.

    `.env` files get every value redacted (see redact_env); any other secret
    file gets the regular pattern scan. Returns the same shape as
    redact_secrets(), with one ENV_VALUE entry per redacted dotenv value.
    """
    names: list[str] = []
    if is_env_file(rel):
        text, count = redact_env(text)
        names.extend([ENV_VALUE] * count)
    text, matched = redact_secrets(text)
    names.extend(matched)
    return text, names
