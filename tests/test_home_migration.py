"""Tests for the one-shot pre-rename home migration (``matlens migrate home``).

The migration is the only code in the rename that *writes* to a user's data
directory, so the safety contract is what these tests actually protect:

* nothing is deleted,
* nothing in the canonical tree is overwritten,
* runtime subtrees (venv/node/bin) are never copied,
* the default is a dry run,
* a failure on one file does not abort the whole migration.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from matlens_cli.home_migration import (
    EXCLUDED_DIR_NAMES,
    MIGRATED_MARKER_NAME,
    apply_home_migration,
    format_report,
    plan_home_migration,
)


@pytest.fixture()
def trees(tmp_path: Path) -> tuple[Path, Path]:
    """A pre-rename home and an empty canonical home."""
    legacy = tmp_path / "hermes"
    canonical = tmp_path / "matlens"
    legacy.mkdir()
    canonical.mkdir()
    return legacy, canonical


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestPlanIsReadOnly:
    def test_plan_writes_nothing(self, trees: tuple[Path, Path]) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "model: x\n")
        _write(legacy / ".env", "KEY=1\n")

        before = sorted(p.name for p in legacy.rglob("*"))
        plan_home_migration(legacy, canonical)

        assert sorted(p.name for p in legacy.rglob("*")) == before
        assert list(canonical.iterdir()) == []

    def test_plan_reports_what_would_be_copied(self, trees: tuple[Path, Path]) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "model: x\n")
        _write(legacy / "sessions" / "a.md", "hi\n")

        report = plan_home_migration(legacy, canonical)

        assert set(report.copied) == {"config.yaml", "sessions/a.md"}
        assert report.dry_run is True
        assert report.failed == []


class TestConflictPolicy:
    def test_existing_canonical_file_is_never_overwritten(
        self, trees: tuple[Path, Path]
    ) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "OLD\n")
        _write(canonical / "config.yaml", "NEW\n")

        apply_home_migration(legacy, canonical)

        # The canonical tree is the one the running system reads — it wins.
        assert (canonical / "config.yaml").read_text(encoding="utf-8") == "NEW\n"
        # The legacy tree keeps its content too: nothing is deleted.
        assert (legacy / "config.yaml").read_text(encoding="utf-8") == "OLD\n"

    def test_identical_file_is_reported_not_recopied(
        self, trees: tuple[Path, Path]
    ) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "same\n")
        _write(canonical / "config.yaml", "same\n")

        report = apply_home_migration(legacy, canonical)

        assert "config.yaml" in report.skipped_identical
        assert "config.yaml" not in report.copied

    def test_conflicting_file_is_listed(self, trees: tuple[Path, Path]) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "OLD\n")
        _write(canonical / "config.yaml", "NEW\n")

        report = apply_home_migration(legacy, canonical)

        assert "config.yaml" in report.skipped_conflicts


class TestRuntimeDirsAreExcluded:
    @pytest.mark.parametrize("name", sorted(EXCLUDED_DIR_NAMES))
    def test_excluded_subtree_is_not_copied(
        self, trees: tuple[Path, Path], name: str
    ) -> None:
        legacy, canonical = trees
        _write(legacy / name / "big.bin", "x" * 100)
        _write(legacy / "config.yaml", "keep\n")

        apply_home_migration(legacy, canonical)

        assert not (canonical / name).exists()
        assert (canonical / "config.yaml").exists()

    def test_nested_file_under_excluded_dir_is_not_copied(
        self, trees: tuple[Path, Path]
    ) -> None:
        legacy, canonical = trees
        _write(legacy / "venv" / "lib" / "site-packages" / "x.py", "code\n")

        apply_home_migration(legacy, canonical)

        assert not (canonical / "venv").exists()


class TestNothingIsDeleted:
    def test_legacy_tree_survives_the_migration(
        self, trees: tuple[Path, Path]
    ) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "data\n")
        _write(legacy / "memories" / "m.md", "memory\n")

        apply_home_migration(legacy, canonical)

        assert (legacy / "config.yaml").exists()
        assert (legacy / "memories" / "m.md").exists()

    def test_migrated_marker_is_written(self, trees: tuple[Path, Path]) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "data\n")

        apply_home_migration(legacy, canonical)

        marker = legacy / MIGRATED_MARKER_NAME
        assert marker.exists()
        assert str(canonical) in marker.read_text(encoding="utf-8")


class TestIdempotency:
    def test_running_twice_is_a_noop_the_second_time(
        self, trees: tuple[Path, Path]
    ) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "data\n")

        first = apply_home_migration(legacy, canonical)
        assert first.copied == ["config.yaml"]

        second = apply_home_migration(legacy, canonical)
        assert second.copied == []
        assert "config.yaml" in second.skipped_identical

    def test_marker_is_not_recreated(self, trees: tuple[Path, Path]) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "data\n")

        apply_home_migration(legacy, canonical)
        marker = legacy / MIGRATED_MARKER_NAME
        marker.write_text("sentinel", encoding="utf-8")

        apply_home_migration(legacy, canonical)

        assert marker.read_text(encoding="utf-8") == "sentinel"


class TestFailureHandling:
    def test_one_failure_does_not_abort_the_rest(
        self, trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        legacy, canonical = trees
        _write(legacy / "a.txt", "a\n")
        _write(legacy / "b.txt", "b\n")
        _write(legacy / "c.txt", "c\n")

        real_copy2 = __import__("shutil").copy2

        def flaky(src, dst, *args, **kwargs):
            if str(src).endswith("b.txt"):
                raise OSError("simulated failure")
            return real_copy2(src, dst, *args, **kwargs)

        monkeypatch.setattr("matlens_cli.home_migration.shutil.copy2", flaky)

        report = apply_home_migration(legacy, canonical)

        assert len(report.failed) == 1
        assert report.failed[0][0] == "b.txt"
        # The other two still made it.
        assert (canonical / "a.txt").exists()
        assert (canonical / "c.txt").exists()

    def test_missing_legacy_tree_produces_empty_report(self, tmp_path: Path) -> None:
        legacy = tmp_path / "does-not-exist"
        canonical = tmp_path / "matlens"

        report = plan_home_migration(legacy, canonical)

        assert report.copied == []
        assert report.failed == []
        assert not canonical.exists()


class TestSymlinks:
    def test_symlink_is_copied_as_a_symlink(self, trees: tuple[Path, Path]) -> None:
        legacy, canonical = trees
        target = _write(legacy / "real.txt", "real\n")
        try:
            os.symlink(target, legacy / "link.txt")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")

        apply_home_migration(legacy, canonical)

        link = canonical / "link.txt"
        assert link.is_symlink()
        # The link target is absolute here, so it still resolves.
        assert link.read_text(encoding="utf-8") == "real\n"


class TestReportFormatting:
    def test_dry_run_report_says_nothing_was_written(
        self, trees: tuple[Path, Path]
    ) -> None:
        legacy, canonical = trees
        _write(legacy / "config.yaml", "data\n")

        text = format_report(plan_home_migration(legacy, canonical))

        assert "Dry run" in text
        assert "--apply" in text

    def test_missing_legacy_reports_nothing_to_migrate(self, tmp_path: Path) -> None:
        text = format_report(
            plan_home_migration(tmp_path / "nope", tmp_path / "matlens")
        )

        assert "nothing to migrate" in text.lower()
