"""CLI handlers for ``matlens migrate ...``.

Exposes ``matlens migrate xai`` — diagnoses and (with --apply) rewrites
references to xAI models retired on May 15, 2026 — and ``matlens migrate
home`` — copies a pre-rename home tree into the canonical one.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from matlens_cli.colors import Colors, color
from matlens_cli.config import load_config


def cmd_migrate(args: Any) -> int:
    """Dispatcher for ``matlens migrate <subtype>``."""
    sub = getattr(args, "migrate_type", None)
    if sub == "xai":
        return cmd_migrate_xai(args)
    if sub == "home":
        return cmd_migrate_home(args)

    print(
        "usage: matlens migrate {xai [--apply] [--no-backup] | home [--apply]}",
        file=sys.stderr,
    )
    return 2


def cmd_migrate_xai(args: Any) -> int:
    """Run xAI May-15 model migration in dry-run or apply mode."""
    from matlens_cli.xai_retirement import (
        MIGRATION_GUIDE_URL,
        RETIREMENT_DATE,
        apply_migration,
        find_retired_xai_refs,
        format_issue,
    )

    apply = bool(getattr(args, "apply", False))
    no_backup = bool(getattr(args, "no_backup", False))

    config = load_config()
    issues = find_retired_xai_refs(config)

    print()
    print(color(
        f"◆ xAI Model Retirement Migration ({RETIREMENT_DATE})",
        Colors.CYAN, Colors.BOLD,
    ))
    print()

    if not issues:
        print(f"  {color('✓', Colors.GREEN)} No retired xAI models in config — nothing to migrate.")
        return 0

    print(f"  Found {len(issues)} retired xAI model reference(s):")
    print()
    for issue in issues:
        print(f"    {color('⚠', Colors.YELLOW)} {format_issue(issue)}")
    print()
    print(f"    {color('→', Colors.CYAN)} Migration guide: {MIGRATION_GUIDE_URL}")
    print()

    config_path = _resolve_config_path()

    if not apply:
        print(color("Dry-run mode — no changes written.", Colors.DIM))
        print(color(
            "Re-run with `matlens migrate xai --apply` to rewrite "
            f"{config_path} in-place (backup created automatically).",
            Colors.DIM,
        ))
        return 0

    if not config_path or not config_path.exists():
        print(
            f"  {color('✗', Colors.RED)} Could not locate config.yaml "
            f"(looked at: {config_path})",
            file=sys.stderr,
        )
        return 1

    try:
        result = apply_migration(
            config_path=config_path,
            issues=issues,
            backup=not no_backup,
        )
    except Exception as exc:
        print(
            f"  {color('✗', Colors.RED)} Migration failed: {exc}",
            file=sys.stderr,
        )
        return 1

    if not result.config_changed:
        print(f"  {color('⚠', Colors.YELLOW)} No changes written.")
        return 0

    if result.backup_path is not None:
        print(f"  {color('✓', Colors.GREEN)} Backup: {result.backup_path}")
    print(
        f"  {color('✓', Colors.GREEN)} Updated {len(result.issues_resolved)} "
        f"slot(s) in {result.file_path}"
    )
    print()
    print(color(
        "Run `matlens doctor` to confirm no retired xAI models remain.",
        Colors.DIM,
    ))
    return 0


def _resolve_config_path() -> Path:
    """Best-effort: locate the active config.yaml on disk."""
    from matlens_cli.config import get_matlens_home

    return get_matlens_home() / "config.yaml"


def cmd_migrate_home(args: Any) -> int:
    """Copy a pre-rename home tree (``~/.hermes``) into the canonical one.

    Dry-run by default. ``--apply`` performs the copy. Nothing is ever
    deleted and an existing canonical file always wins.
    """
    from matlens_cli.home_migration import (
        apply_home_migration,
        format_report,
        plan_home_migration,
    )

    apply = bool(getattr(args, "apply", False))

    legacy_home, canonical_home = _resolve_migration_homes()

    print()
    print(color("◆ MatLens Home Migration", Colors.CYAN, Colors.BOLD))
    print()

    if legacy_home is None:
        print(
            f"  {color('✓', Colors.GREEN)} No pre-rename MatLens home directory found "
            "— nothing to migrate."
        )
        return 0

    try:
        report = (
            apply_home_migration(legacy_home, canonical_home)
            if apply
            else plan_home_migration(legacy_home, canonical_home)
        )
    except Exception as exc:
        print(f"  {color('✗', Colors.RED)} Migration failed: {exc}", file=sys.stderr)
        return 1

    for line in format_report(report).splitlines():
        print(f"  {line}")

    if report.failed:
        return 1

    if not apply and report.has_work:
        print()
        print(color(
            "Re-run with `matlens migrate home --apply` to copy the files.",
            Colors.DIM,
        ))

    return 0


def _resolve_migration_homes() -> tuple[Path | None, Path]:
    """Locate the legacy home tree and the canonical home.

    Returns ``(None, canonical)`` when there is no legacy tree to migrate
    from.
    """
    from matlens_constants import _get_platform_default_matlens_home, _legacy_matlens_home_roots

    canonical = Path(_get_platform_default_matlens_home())

    for legacy in _legacy_matlens_home_roots():
        if legacy.is_dir():
            return legacy, canonical

    return None, canonical
