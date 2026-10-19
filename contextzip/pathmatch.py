"""
pathmatch.py — Work out where each file in an AI-returned ZIP belongs.

AI tools don't hand ZIPs back in a consistent shape. The same change can
come back as

    frontend/src/app/page.tsx        exactly as sent
    my-app/frontend/src/app/page.tsx wrapped in an extra folder (or two)
    src/app/page.tsx                 relative to a subfolder
    page.tsx                         flattened to bare file names
    frontend\\src\\app\\page.tsx       with Windows separators

Exact-path matching turns all but the first into a pile of "new" files.
Instead, each name is matched against the project's real paths (the files
that were sent, plus what's on disk) by its longest shared path *suffix*,
and every confident match votes for a rewrite rule: "drop this leading
part, add that one". The winning rule is then applied to everything else in
the ZIP — including brand-new files, which have nothing to match on their
own — so `src/lib/new.ts` lands next to its siblings in
`frontend/src/lib/new.ts` instead of a stray `src/` folder at the root.

When a name still fits several files equally well (three different
`page.tsx`), the file's content decides if one candidate is clearly the
closest; otherwise the entry is reported as ambiguous and never written
anywhere on a guess.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable

# Zip noise that is never part of the answer.
_JUNK_PREFIXES = ("__MACOSX/",)
_JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
# Never written into, whatever the zip says.
_FORBIDDEN_TOP = {".git", ".contextzip"}


@dataclass(frozen=True)
class Rule:
    """Rewrite `drop/...rest` to `add/...rest`."""

    drop: str  # "" or "a/b"
    add: str  # "" or "x/y"

    def applies(self, name: str) -> bool:
        return not self.drop or name.startswith(self.drop + "/")

    def apply(self, name: str) -> str:
        rest = name[len(self.drop) + 1:] if self.drop else name
        return f"{self.add}/{rest}" if self.add else rest

    @property
    def is_identity(self) -> bool:
        return not self.drop and not self.add

    def describe(self) -> str:
        left = f"{self.drop}/…" if self.drop else "…"
        right = f"{self.add}/…" if self.add else "…"
        return f"{left} → {right}"


@dataclass
class Match:
    name: str
    """Normalised name inside the zip."""
    target: str | None
    """Project-relative path to write to; None when ambiguous."""
    how: str
    """exact | rule | suffix | content | new | ambiguous"""
    candidates: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    matches: list[Match]
    rule: Rule | None
    """The rewrite rule inferred for this zip, if any (None = paths used as-is)."""
    skipped: list[str] = field(default_factory=list)
    """Zip entries ignored as noise (__MACOSX/, .DS_Store, …)."""


def normalize_name(name: str) -> str | None:
    """Clean a zip entry name; None if it's noise or a directory."""
    n = name.replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    n = n.lstrip("/")
    if not n or n.endswith("/"):
        return None
    if any(n.startswith(p) for p in _JUNK_PREFIXES):
        return None
    if n.rsplit("/", 1)[-1] in _JUNK_NAMES:
        return None
    return n


def is_forbidden(target: str) -> bool:
    return target.split("/", 1)[0] in _FORBIDDEN_TOP


def _common_suffix(a: list[str], b: list[str]) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _similarity(a: bytes, b: bytes) -> float:
    if a == b:
        return 1.0
    if len(a) > 400_000 or len(b) > 400_000:
        return 0.0
    try:
        ta, tb = a.decode("utf-8"), b.decode("utf-8")
    except UnicodeDecodeError:
        return 0.0
    la, lb = ta.splitlines(), tb.splitlines()
    sm = SequenceMatcher(None, la, lb, autojunk=False)
    return sm.ratio()


def match_paths(
    names: list[str],
    known: set[str],
    *,
    sent: set[str] | None = None,
    read_entry: Callable[[str], bytes] | None = None,
    read_known: Callable[[str], bytes | None] | None = None,
) -> MatchResult:
    """
    Map zip entry *names* onto project paths.

    known       every path the project has (sent files + files on disk)
    sent        the subset that was in the zip you sent; preferred when a
                name fits several files, since the AI most likely returned
                what it was given
    read_entry  returns a zip entry's bytes (for content tie-breaks)
    read_known  returns a project file's bytes, or None
    """
    sent = sent or set()
    by_base: dict[str, list[str]] = defaultdict(list)
    for k in known:
        by_base[k.rsplit("/", 1)[-1]].append(k)

    cleaned: list[str] = []
    skipped: list[str] = []
    for raw in names:
        n = normalize_name(raw)
        if n is None:
            if not raw.endswith("/"):
                skipped.append(raw)
            continue
        cleaned.append(n)

    # ── 1. Best suffix candidates per name, and votes for a rewrite rule ─────
    best: dict[str, tuple[int, list[str]]] = {}
    votes: dict[Rule, int] = defaultdict(int)
    for n in cleaned:
        segs = n.split("/")
        scored = [(_common_suffix(segs, k.split("/")), k) for k in by_base.get(segs[-1], [])]
        if not scored:
            best[n] = (0, [])
            continue
        top = max(s for s, _ in scored)
        cands = [k for s, k in scored if s == top]
        if len(cands) > 1 and sent:
            preferred = [k for k in cands if k in sent]
            cands = preferred or cands
        best[n] = (top, cands)
        if len(cands) == 1:
            k_segs = cands[0].split("/")
            rule = Rule("/".join(segs[:-top]), "/".join(k_segs[:-top]))
            votes[rule] += top

    rule: Rule | None = None
    if votes:
        # Ties go to "paths are fine as they are".
        winner, weight = max(votes.items(), key=lambda kv: (kv[1], kv[0].is_identity))
        # A rule only generalises to unmatched (new) files when it's backed
        # by real path structure — at least a folder plus a file name's
        # worth of agreement — not by one bare file name.
        if not winner.is_identity and weight >= 2:
            rule = winner

    # ── 2. Resolve each name ─────────────────────────────────────────────────
    matches: list[Match] = []
    for n in cleaned:
        top, cands = best[n]

        if n in known and (rule is None or not rule.applies(n) or rule.apply(n) not in known):
            matches.append(Match(n, n, "exact"))
            continue

        if rule is not None and rule.applies(n) and rule.apply(n) in known:
            matches.append(Match(n, rule.apply(n), "rule"))
            continue

        if len(cands) == 1:
            matches.append(Match(n, cands[0], "suffix"))
            continue

        if len(cands) > 1:
            choice = _pick_by_content(n, cands, read_entry, read_known)
            if choice is not None:
                matches.append(Match(n, choice, "content", candidates=cands))
            else:
                matches.append(Match(n, None, "ambiguous", candidates=sorted(cands)))
            continue

        # Nothing like it in the project: a new file.
        target = rule.apply(n) if rule is not None and rule.applies(n) else n
        matches.append(Match(n, target, "new"))

    # ── 3. Two entries must never land on the same file ──────────────────────
    rank = {"exact": 0, "rule": 1, "suffix": 2, "content": 3, "new": 4}
    owners: dict[str, Match] = {}
    for m in sorted(matches, key=lambda m: rank.get(m.how, 9)):
        if m.target is None:
            continue
        if m.target in owners:
            m.candidates = [m.target]
            m.target = None
            m.how = "ambiguous"
        else:
            owners[m.target] = m

    for m in matches:
        if m.target is not None and is_forbidden(m.target):
            m.target = None
            m.how = "ambiguous"

    return MatchResult(matches=matches, rule=rule, skipped=skipped)


def _pick_by_content(
    name: str,
    cands: list[str],
    read_entry: Callable[[str], bytes] | None,
    read_known: Callable[[str], bytes | None] | None,
) -> str | None:
    """The candidate whose content is clearly closest to the entry, or None."""
    if read_entry is None or read_known is None:
        return None
    try:
        incoming = read_entry(name)
    except (OSError, KeyError):
        return None
    scores: list[tuple[float, str]] = []
    for c in cands:
        data = read_known(c)
        if data is None:
            continue
        scores.append((_similarity(incoming, data), c))
    if not scores:
        return None
    scores.sort(reverse=True)
    best_score, best = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    if best_score >= 0.5 and best_score - runner_up >= 0.15:
        return best
    return None
