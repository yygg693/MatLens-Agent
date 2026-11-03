"""One-shot migration of a pre-rename home tree into the canonical one.

Why this exists
---------------
Before the rename, MatLens kept its user data under ``~/.hermes`` (or
``%LOCALAPPDATA%\\hermes`` on Windows). The canonical location is now
``~/.matlens``. The read-only fallback already implemented in
:mod:`matlens_constants` keeps the legacy tree reachable — the backend, the
desktop and the installer all resolve to the same directory, and an old tree
is honoured only when it actually exists.

That fallback is deliberately *read-only*. It never moves anything, because
silently relocating a user's config, API keys, memories and sessions is the
one failure mode the rename must never cause: a half-finished move leaves
both trees half-broken.

This module provides the explicit, user-triggered second half:
``matlens migrate home --apply``.

Safety contract
---------------
* **Never deletes.** The legacy tree is copied, never moved or removed. The
  user keeps a working fallback if anything goes wrong.
* **Never overwrites.** A file that already exists in the canonical tree is
  left alone and reported as a conflict. The canonical tree is the one the
  running system reads, so it wins.
* **Never fails hard.** Every failure is collected and reported. A single
  unreadable file does not abort the migration.
* **Dry-run by default.** ``--apply`` is required to write anything.
* **Idempotent.** Running it twice is a no-op the second time.

What gets copied
----------------
Only the user-owned state that lives directly in the home root. The
``venv``/``node``/``bin`` subtrees are **not** copied: they are rebuilt by the
installer, they are large, and copying a venv between machines or Python
versions produces a broken environment.
"""

from __future__ import annotations

import filecmp
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

#: Subdirectories of the home root that are NEVER copied. These are runtime
#: artifacts, not user data — the installer regenerates them.
EXCLUDED_DIR_NAMES = frozenset(
    {
        "venv",
        "node",
        "bin",
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)

#: Subdirectories of the home root that are copied but only when absent in
#: the canonical tree — i.e. the canonical tree wins on conflict.
#:
#: (No such directories today. The list exists so the conflict policy has one
#: obvious home if a future release needs to treat a subtree specially.)
PREFER_CANONICAL_DIRS: frozenset[str] = frozenset()

#: Marker file dropped into the legacy tree after a successful migration.
MIGRATED_MARKER_NAME = "README_MIGRATED"

_MIGRATED_MARKER_BODY = """\
This directory was the MatLens (then Hermes) data directory before the
product was renamed.

Its contents were COPIED into the canonical MatLens home directory:

    {canonical}

Nothing here was deleted. MatLens now reads the canonical directory; this
copy is kept as a fallback (and so the migration can be inspected).

If the canonical directory is ever lost, restore from here.
"""


@dataclass
class MigrationReport:
    """Outcome of a home migration attempt."""

    legacy_home: Path | None = None
    canonical_home: Path | None = None
    copied: list[str] = field(default_factory=list)
    skipped_conflicts: list[str] = field(default_factory=list)
    skipped_identical: list[str] = field(default_factory=list)
    skipped_excluded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    dry_run: bool = True

    @property
    def has_work(self) -> bool:
        """True when there is at least one file worth copying."""
        return bool(self.copied) or bool(self.failed)

    @property
    def total_candidates(self) -> int:
        return (
            len(self.copied)
            + len(self.skipped_conflicts)
            + len(self.skipped_identical)
            + len(self.failed)
        )


def _is_excluded(name: str) -> bool:
    return name in EXCLUDED_DIR_NAMES


def _files_identical(src: Path, dst: Path) -> bool:
    """Cheap identity check that never raises."""
    try:
        if not dst.is_file():
            return False
        if src.stat().st_size != dst.stat().st_size:
            return False
        return filecmp.cmp(src, dst, shallow=False)
    except OSError:
        return False


def _relative_files(legacy: Path) -> list[Path]:
    """List every file under ``legacy``, relative to it, excluding runtime dirs.

    Symlinks are reported but never followed — a symlinked config that points
    outside the home tree would otherwise be copied as a broken relative link
    or, worse, followed into an unrelated directory.
    """
    results: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(legacy, followlinks=False):
        current = Path(dirpath)

        # Prune excluded subtrees in place so os.walk never descends into them.
        dirnames[:] = sorted(d for d in dirnames if not _is_excluded(d))

        for name in sorted(filenames):
            # Our own migration breadcrumb is not user data — copying it into
            # the canonical tree would litter it with a marker that describes
            # a directory it no longer relates to.
            if name == MIGRATED_MARKER_NAME:
                continue
            rel = (current / name).relative_to(legacy)
            results.append(rel)

    return results


def plan_home_migration(legacy_home: Path, canonical_home: Path) -> MigrationReport:
    """Inspect both trees and report what a migration would do.

    Pure read-only: no file is created, modified or removed.
    """
    report = MigrationReport(
        legacy_home=legacy_home, canonical_home=canonical_home, dry_run=True
    )

    if not legacy_home.is_dir():
        return report

    for rel in _relative_files(legacy_home):
        rel_str = rel.as_posix()

        if any(_is_excluded(part) for part in rel.parts[:-1]):
            report.skipped_excluded.append(rel_str)
            continue

        src = legacy_home / rel
        dst = canonical_home / rel

        if dst.exists():
            if _files_identical(src, dst):
                report.skipped_identical.append(rel_str)
            else:
                report.skipped_conflicts.append(rel_str)
            continue

        report.copied.append(rel_str)

    return report


def apply_home_migration(legacy_home: Path, canonical_home: Path) -> MigrationReport:
    """Copy the legacy tree into the canonical one.

    Never deletes, never overwrites, never raises for an individual file.
    """
    report = plan_home_migration(legacy_home, canonical_home)
    report.dry_run = False

    if not legacy_home.is_dir():
        return report

    try:
        canonical_home.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        report.failed.append(("<home>", str(exc)))
        return report

    # Iterate over a COPY: `report.copied` is mutated inside the loop (a
    # failure or a conflict removes the entry), and mutating a list while
    # iterating it silently skips the next element — which would leave files
    # uncopied without any error.
    for rel_str in list(report.copied):
        rel = Path(rel_str)
        src = legacy_home / rel
        dst = canonical_home / rel

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Symlinks are copied as symlinks (never dereferenced) so a link
            # that points outside the home tree keeps pointing where it did.
            if src.is_symlink():
                link_target = os.readlink(src)
                if dst.exists() or dst.is_symlink():
                    # A pre-existing destination wins — same conflict policy
                    # as an identical file.
                    report.skipped_conflicts.append(rel_str)
                    report.copied.remove(rel_str)
                    continue
                os.symlink(link_target, dst)
                continue
            shutil.copy2(src, dst)
        except OSError as exc:
            report.failed.append((rel_str, str(exc)))
            report.copied.remove(rel_str)

    # Drop a breadcrumb in the legacy tree so a user who finds it knows what
    # happened. Best-effort: never fail the migration over it.
    try:
        marker = legacy_home / MIGRATED_MARKER_NAME
        if not marker.exists():
            marker.write_text(
                _MIGRATED_MARKER_BODY.format(canonical=canonical_home),
                encoding="utf-8",
            )
    except OSError:
        pass

    return report


def format_report(report: MigrationReport) -> str:
    """Render a migration report as human-readable text."""
    lines: list[str] = []

    legacy = report.legacy_home
    canonical = report.canonical_home

    if legacy is None or not legacy.is_dir():
        return "No pre-rename MatLens home directory found — nothing to migrate."

    verb = "Would copy" if report.dry_run else "Copied"

    lines.append(f"Legacy home:      {legacy}")
    lines.append(f"Canonical home:   {canonical}")
    lines.append("")

    if report.copied:
        lines.append(f"{verb} {len(report.copied)} file(s):")
        for name in report.copied:
            lines.append(f"  + {name}")
        lines.append("")

    if report.skipped_identical:
        lines.append(f"Already identical: {len(report.skipped_identical)} file(s)")
        lines.append("")

    if report.skipped_conflicts:
        lines.append(
            f"Conflicts (canonical version kept): {len(report.skipped_conflicts)} file(s)"
        )
        for name in report.skipped_conflicts:
            lines.append(f"  = {name}")
        lines.append("")

    if report.skipped_excluded:
        lines.append(
            f"Skipped runtime dirs (rebuilt by the installer): "
            f"{len(report.skipped_excluded)} entr(ies)"
        )
        lines.append("")

    if report.failed:
        lines.append(f"FAILED: {len(report.failed)} file(s)")
        for name, err in report.failed:
            lines.append(f"  ! {name}: {err}")
        lines.append("")

    if report.dry_run:
        lines.append("Dry run — nothing was written. Re-run with --apply to migrate.")
    elif report.copied:
        lines.append(
            "Migration complete. The legacy directory was left in place as a fallback."
        )
    elif report.failed:
        lines.append("Migration finished with errors; the legacy directory was left intact.")
    else:
        lines.append("Nothing to do — the canonical home already has every file.")

    return "\n".join(lines)
