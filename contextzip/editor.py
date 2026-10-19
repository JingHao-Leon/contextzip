"""
editor.py — Resolve apply-zip's risky files in your code editor.

VS Code and its forks (Cursor, Windsurf, VSCodium) ship a three-way merge
editor that can be opened from the command line:

    code --wait --merge <yours> <incoming> <base> <result>

That's exactly the shape of an apply-zip conflict: your file on disk, the
AI's version, and the version you originally sent. The result is your real
file, so finishing the merge in the editor *is* the resolution — apply-zip
then leaves that file alone.

Files that can't be merged (a partial file, one with no baseline, one you
deleted) open as a side-by-side diff instead, and the terminal asks what
to keep.

The editor is found from CONTEXTZIP_EDITOR, then code, cursor, windsurf,
codium and code-insiders on your PATH.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from contextzip.applier import ApplyEntry, ApplyPlan, FileStatus

EDITOR_ENV_VAR = "CONTEXTZIP_EDITOR"
_CANDIDATES = ("code", "cursor", "windsurf", "codium", "code-insiders")


def find_editor() -> list[str] | None:
    """The editor command as an argv prefix, or None if none is available."""
    custom = os.environ.get(EDITOR_ENV_VAR, "").strip()
    if custom:
        parts = shlex.split(custom, posix=os.name != "nt")
        if parts and shutil.which(parts[0]):
            return [shutil.which(parts[0]) or parts[0], *parts[1:]]
    for name in _CANDIDATES:
        found = shutil.which(name)
        if found:
            return [found]
    return None


def editor_name(cmd: list[str]) -> str:
    stem = Path(cmd[0]).stem.lower()
    return {"code": "VS Code", "cursor": "Cursor", "windsurf": "Windsurf", "codium": "VSCodium"}.get(stem, stem)


def _run(cmd: list[str]) -> bool:
    try:
        # .cmd shims on Windows need the shell to run; the args are paths we
        # created ourselves plus a fixed set of flags.
        subprocess.run(cmd, check=False, shell=os.name == "nt")
        return True
    except OSError:
        return False


def _temp(dirpath: Path, label: str, rel: str, data: bytes | str | None) -> Path:
    name = rel.replace("/", "__")
    path = dirpath / f"{label}__{name}"
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8", newline="")
    else:
        path.write_bytes(data or b"")
    return path


def open_merge(cmd: list[str], entry: ApplyEntry, project_dir: Path, workdir: Path) -> bool:
    """
    Open a conflict in the three-way merge editor, blocking until it's closed.
    Returns True if the file on disk changed (the merge was completed).
    """
    live = project_dir / entry.rel_path
    before = live.read_bytes() if live.is_file() else b""
    yours = _temp(workdir, "yours", entry.rel_path, before)
    incoming = _temp(workdir, "incoming", entry.rel_path, entry.incoming)
    base = _temp(workdir, "original", entry.rel_path, entry.base_text or "")
    if not _run([*cmd, "--wait", "--merge", str(yours), str(incoming), str(base), str(live)]):
        return False
    after = live.read_bytes() if live.is_file() else b""
    return after != before


def open_diff(cmd: list[str], entry: ApplyEntry, project_dir: Path, workdir: Path) -> bool:
    """Open your file next to the AI's version, blocking until it's closed."""
    live = project_dir / entry.rel_path
    left = live if live.is_file() else _temp(workdir, "missing", entry.rel_path, b"")
    right = _temp(workdir, "incoming", entry.rel_path, entry.incoming)
    return _run([*cmd, "--wait", "--diff", str(left), str(right)])


def resolve_in_editor(plan: ApplyPlan, project_dir: Path, ask) -> dict:
    """
    Walk the plan's risky entries in the editor. Returns decisions for
    execute_plan. *ask(entry) -> "theirs" | "keep"* is called for entries
    that open as a plain diff.
    """
    cmd = find_editor()
    if cmd is None:
        raise FileNotFoundError("no editor found")

    decisions: dict = {}
    with tempfile.TemporaryDirectory(prefix="contextzip-review-") as tmp:
        workdir = Path(tmp)
        for entry in plan.risky_entries:
            if not entry.rel_path:
                decisions[entry.display_path] = "skip"
                continue
            mergeable = entry.status in (FileStatus.CONFLICT, FileStatus.DRIFTED) and entry.base_text is not None
            if mergeable:
                changed = open_merge(cmd, entry, project_dir, workdir)
                decisions[entry.display_path] = "keep" if changed else ask(entry)
            else:
                open_diff(cmd, entry, project_dir, workdir)
                decisions[entry.display_path] = ask(entry)
    return decisions
