"""
snapshots.py — Versioned packages.

Every ZIP contextzip makes becomes a numbered snapshot: a copy of the ZIP
plus its manifest, kept under .contextzip/snapshots/. That's what lets
apply-zip merge an AI reply against exactly what was sent — even if you've
packaged again since, which used to overwrite the only copy.

    .contextzip/snapshots/
      index.json        {"next": 15}
      0014/
        snapshot.json   the manifest (see applier.write_manifest)
        files.zip       the ZIP that was sent

Each snapshot has a short ID (#14) and a random token; together they print
as "14-k3f9a2". The token goes into the CONTEXTZIP.md inside the ZIP (see
guide.py), so when an AI reply echoes that file back, apply-zip knows the
exact snapshot it answers — and the token keeps that unambiguous across
machines and clones, where plain numbers would collide.

Snapshots are local, never uploaded, and pruned automatically (see
`prune_candidates` and cleanup.py) — but never one a ZIP in the inbox is
still waiting to be applied against.
"""

from __future__ import annotations

import json
import secrets
import shutil
import string
import time
from dataclasses import dataclass
from pathlib import Path

SNAPSHOTS_DIRNAME = "snapshots"
_INDEX_NAME = "index.json"
_MANIFEST_NAME = "snapshot.json"
_ZIP_NAME = "files.zip"
_TOKEN_ALPHABET = string.ascii_lowercase + string.digits
_TOKEN_LENGTH = 6
# A reserved snapshot whose ZIP never got written (a crash mid-package) is
# cleaned up once it's this old.
_STALE_RESERVATION_SECONDS = 60 * 60


@dataclass
class Snapshot:
    id: int
    token: str
    dir: Path

    @property
    def label(self) -> str:
        return f"{self.id}-{self.token}"

    @property
    def manifest_path(self) -> Path:
        return self.dir / _MANIFEST_NAME

    @property
    def zip_path(self) -> Path:
        return self.dir / _ZIP_NAME

    def load(self) -> dict:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def is_complete(self) -> bool:
        return self.manifest_path.is_file() and self.zip_path.is_file()


def snapshots_dir(project_dir: Path) -> Path:
    from contextzip.packager import _workspace_dir  # lazy: packager imports this module

    workspace, _ = _workspace_dir(project_dir)
    return workspace / SNAPSHOTS_DIRNAME


def _read_next(sdir: Path) -> int:
    try:
        data = json.loads((sdir / _INDEX_NAME).read_text(encoding="utf-8"))
        n = int(data.get("next", 1))
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        n = 1
    existing = [int(p.name) for p in sdir.iterdir() if p.is_dir() and p.name.isdigit()] if sdir.is_dir() else []
    return max([n, *(e + 1 for e in existing)])


def reserve(project_dir: Path) -> Snapshot:
    """
    Claim the next snapshot ID and create its folder. Called before the ZIP
    is written, because the ZIP's CONTEXTZIP.md carries the ID. Safe against
    two runs at once: the folder is created exclusively, and a taken ID
    simply moves on to the next.
    """
    sdir = snapshots_dir(project_dir)
    sdir.mkdir(parents=True, exist_ok=True)
    n = _read_next(sdir)
    while True:
        folder = sdir / f"{n:04d}"
        try:
            folder.mkdir()
            break
        except FileExistsError:
            n += 1
    try:
        (sdir / _INDEX_NAME).write_text(json.dumps({"next": n + 1}), encoding="utf-8")
    except OSError:
        pass
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))
    return Snapshot(id=n, token=token, dir=folder)


def finalize(snapshot: Snapshot, zip_path: Path, manifest: dict, *, mode: str) -> Path:
    """Copy the ZIP into the snapshot and write its manifest."""
    shutil.copyfile(zip_path, snapshot.zip_path)
    manifest = dict(manifest)
    manifest.update(
        {
            "snapshot_id": snapshot.id,
            "token": snapshot.token,
            "mode": mode,
            "status": "pending",
            "zip_path": str(snapshot.zip_path.resolve()),
            "sent_zip_path": str(zip_path.resolve()),
        }
    )
    snapshot.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return snapshot.manifest_path


def discard(snapshot: Snapshot) -> None:
    shutil.rmtree(snapshot.dir, ignore_errors=True)


def list_snapshots(project_dir: Path, *, complete_only: bool = True) -> list[Snapshot]:
    """Snapshots for this project, newest first."""
    sdir = snapshots_dir(project_dir)
    if not sdir.is_dir():
        return []
    out: list[Snapshot] = []
    for folder in sdir.iterdir():
        if not (folder.is_dir() and folder.name.isdigit()):
            continue
        snap = Snapshot(id=int(folder.name), token="", dir=folder)
        if complete_only and not snap.is_complete:
            continue
        snap.token = str(snap.load().get("token", ""))
        out.append(snap)
    return sorted(out, key=lambda s: s.id, reverse=True)


def find(project_dir: Path, ref: str | int) -> Snapshot | None:
    """
    Look a snapshot up by "14", "#14", "14-k3f9a2" or the bare token. When
    both a number and a token are given they must agree, so a reply from
    another clone (same number, different token) never matches by mistake.
    """
    text = str(ref).strip().lstrip("#")
    number: int | None = None
    token: str | None = None
    if "-" in text:
        head, _, tail = text.partition("-")
        if head.isdigit():
            number, token = int(head), tail.lower()
    elif text.isdigit():
        number = int(text)
    else:
        token = text.lower()

    for snap in list_snapshots(project_dir):
        if number is not None and snap.id != number:
            continue
        if token is not None and snap.token != token:
            continue
        return snap
    return None


def mark_applied(manifest_path: Path) -> None:
    """Record that a reply to this snapshot was applied (best-effort)."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "snapshot_id" not in data:
            return
        data["status"] = "applied"
        data["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass


def created_ts(snapshot: Snapshot) -> float:
    try:
        return snapshot.manifest_path.stat().st_mtime if snapshot.is_complete else snapshot.dir.stat().st_mtime
    except OSError:
        return 0.0


def prune_candidates(
    project_dir: Path,
    *,
    keep: int,
    max_age_days: int,
    protected: set[Path] | None = None,
) -> list[Path]:
    """
    Snapshot folders that can go: not among the newest *keep*, older than
    *max_age_days*, and not *protected* (snapshots a ZIP in the inbox is
    still waiting on). Reservations whose ZIP never got written are also
    removed once they're stale.
    """
    sdir = snapshots_dir(project_dir)
    if not sdir.is_dir():
        return []
    protected = {p.resolve() for p in (protected or set())}
    now = time.time()
    out: list[Path] = []

    for snap in list_snapshots(project_dir, complete_only=False):
        if not snap.is_complete and now - created_ts(snap) > _STALE_RESERVATION_SECONDS:
            out.append(snap.dir)

    complete = list_snapshots(project_dir)
    for index, snap in enumerate(complete):
        if index < keep:
            continue
        if now - created_ts(snap) < max_age_days * 86400:
            continue
        if snap.dir.resolve() in protected:
            continue
        out.append(snap.dir)
    return out


def protected_by_inbox(project_dir: Path) -> set[Path]:
    """
    Snapshot folders that ZIPs waiting in the inbox answer — found from the
    CONTEXTZIP.md they echo back. Kept by cleanup no matter how old.
    """
    from contextzip.applier import inbox_dir  # lazy: applier imports this module
    from contextzip.guide import read_guide_from_zip

    inbox = inbox_dir(project_dir)
    if not inbox.is_dir():
        return set()
    keep: set[Path] = set()
    for zp in inbox.glob("*.zip"):
        guide = read_guide_from_zip(zp)
        if guide and guide.snapshot:
            snap = find(project_dir, guide.snapshot)
            if snap is not None:
                keep.add(snap.dir)
    return keep
