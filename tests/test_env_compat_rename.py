"""Regression tests for the Hermes → MatLens environment-variable alignment.

Background
----------

The upstream project shipped every environment variable under a ``HERMES_``
prefix. MatLens renamed them to ``MATLENS_``, but the rename was applied
independently on the Python side and the Electron side, so for a window of
time the two halves disagreed on the wire. The desktop sent
``HERMES_DASHBOARD_SESSION_TOKEN``; the backend read
``MATLENS_DASHBOARD_SESSION_TOKEN``. The backend therefore ignored the
token entirely, and every gated endpoint answered **401**.

These tests pin the compatibility layer that closes that window:

* the backend accepts either name for the *functional* variables;
* the canonical ``MATLENS_*`` name always wins over the legacy one;
* ``MATLENS_HOME`` is deliberately **not** aliased, because the old and new
  names historically pointed at *different directories* and honouring the
  legacy one would point the backend at an empty tree (making the user's
  config, memories and sessions appear to vanish).
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from matlens_cli.env_compat import LEGACY_ENV_ALIASES, matlens_env, matlens_env_flag

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove every variable this module cares about before each test."""
    for canonical in LEGACY_ENV_ALIASES:
        monkeypatch.delenv(canonical, raising=False)
        monkeypatch.delenv(LEGACY_ENV_ALIASES[canonical], raising=False)


class TestLegacyFallback:
    def test_legacy_name_is_honoured_when_canonical_is_unset(self, monkeypatch):
        monkeypatch.setenv("HERMES_DESKTOP", "1")
        assert matlens_env("MATLENS_DESKTOP") == "1"

    def test_canonical_name_wins_over_legacy(self, monkeypatch):
        monkeypatch.setenv("HERMES_DESKTOP", "1")
        monkeypatch.setenv("MATLENS_DESKTOP", "0")
        assert matlens_env("MATLENS_DESKTOP") == "0"

    def test_blank_canonical_falls_through_to_legacy(self, monkeypatch):
        # A var exported as an empty string must not shadow the legacy value —
        # shell wrappers routinely export empty strings.
        monkeypatch.setenv("MATLENS_DESKTOP", "   ")
        monkeypatch.setenv("HERMES_DESKTOP", "1")
        assert matlens_env("MATLENS_DESKTOP") == "1"

    def test_returns_default_when_neither_is_set(self):
        assert matlens_env("MATLENS_DESKTOP") is None
        assert matlens_env("MATLENS_DESKTOP", "fallback") == "fallback"

    def test_name_without_alias_behaves_like_plain_getenv(self, monkeypatch):
        monkeypatch.setenv("SOME_UNRELATED", "value")
        assert matlens_env("SOME_UNRELATED") == "value"
        assert matlens_env("SOME_OTHER") is None


class TestAliasRegistry:
    def test_matlsens_home_is_not_aliased(self):
        """The path variable must never fall back to the legacy name.

        The backend defaults to ``~/.matlens`` while the desktop used to
        default to ``~/.hermes`` / ``%LOCALAPPDATA%\\hermes``. Aliasing
        ``MATLENS_HOME`` → ``HERMES_HOME`` would redirect the backend into
        an empty directory and make the user's data appear to vanish.
        """
        assert "MATLENS_HOME" not in LEGACY_ENV_ALIASES

    @pytest.mark.parametrize(
        "canonical",
        [
            "MATLENS_DASHBOARD_SESSION_TOKEN",
            "MATLENS_DESKTOP",
            "MATLENS_DESKTOP_READY_FILE",
            "MATLENS_DESKTOP_TERMINAL",
            "MATLENS_WEB_DIST",
        ],
    )
    def test_functional_variables_are_aliased(self, canonical):
        assert canonical in LEGACY_ENV_ALIASES
        assert LEGACY_ENV_ALIASES[canonical].startswith("HERMES_")


class TestTruthyFlag:
    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_spellings(self, monkeypatch, raw):
        monkeypatch.setenv("HERMES_DESKTOP", raw)
        assert matlens_env_flag("MATLENS_DESKTOP") is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "maybe"])
    def test_falsy_spellings(self, monkeypatch, raw):
        monkeypatch.setenv("HERMES_DESKTOP", raw)
        assert matlens_env_flag("MATLENS_DESKTOP") is False

    def test_unset_is_falsy(self):
        assert matlens_env_flag("MATLENS_DESKTOP") is False


class TestBackendReadSites:
    """The backend read sites must go through the compatibility layer."""

    def test_web_server_accepts_legacy_session_header(self):
        """A pre-rename desktop build must still authenticate.

        The backend had already switched to ``X-MatLens-Session-Token``, so
        the old header was silently ignored and every gated endpoint
        answered 401 for those builds.
        """
        from matlens_cli import web_server

        assert web_server._SESSION_HEADER_NAME == "X-MatLens-Session-Token"
        assert web_server._LEGACY_SESSION_HEADER_NAME == "X-Hermes-Session-Token"

    def test_both_session_headers_authenticate(self):
        """Both header spellings must pass the token check.

        Exercised against the live module rather than a reloaded copy:
        reloading ``web_server`` regenerates its module-level session token,
        which leaks into every other test that authenticates with the
        original token and turns them into spurious 401s.
        """
        from fastapi.testclient import TestClient

        from matlens_cli import web_server

        client = TestClient(web_server.app)
        token = web_server._SESSION_TOKEN

        # /api/ssh/ownership is behind the token gate (unlike the public
        # /api/status), so it distinguishes "authenticated" from "not".
        for header in (
            web_server._SESSION_HEADER_NAME,
            web_server._LEGACY_SESSION_HEADER_NAME,
        ):
            resp = client.get("/api/ssh/ownership", headers={header: token})
            assert resp.status_code != 401, f"{header} must authenticate"

        resp = client.get(
            "/api/ssh/ownership",
            headers={web_server._SESSION_HEADER_NAME: "wrong-token"},
        )
        assert resp.status_code == 401, "a wrong token must still be rejected"


class TestSessionTokenResolution:
    """The minted token must honour the legacy env var name."""

    def test_canonical_env_wins(self, monkeypatch):
        from matlens_cli.env_compat import matlens_env

        monkeypatch.setenv("MATLENS_DASHBOARD_SESSION_TOKEN", "canonical-token")
        monkeypatch.setenv("HERMES_DASHBOARD_SESSION_TOKEN", "legacy-token")

        assert matlens_env("MATLENS_DASHBOARD_SESSION_TOKEN") == "canonical-token"

    def test_legacy_env_is_used_when_canonical_absent(self, monkeypatch):
        from matlens_cli.env_compat import matlens_env

        monkeypatch.delenv("MATLENS_DASHBOARD_SESSION_TOKEN", raising=False)
        monkeypatch.setenv("HERMES_DASHBOARD_SESSION_TOKEN", "legacy-token")

        assert matlens_env("MATLENS_DASHBOARD_SESSION_TOKEN") == "legacy-token"


class TestDesktopSpawnContract:
    """The Electron main process must write BOTH names for each variable.

    Writing both keeps the handshake working against a backend of either
    vintage: a renamed backend reads the ``MATLENS_*`` name, an un-renamed
    one reads the ``HERMES_*`` name.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def main_ts(cls):
        from pathlib import Path

        # tests/ -> repo root is one level up from the tests directory.
        repo_root = Path(__file__).resolve().parents[1]
        return (repo_root / "apps" / "desktop" / "electron" / "main.ts").read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "variable",
        [
            "MATLENS_DASHBOARD_SESSION_TOKEN",
            "HERMES_DASHBOARD_SESSION_TOKEN",
            "MATLENS_DESKTOP",
            "HERMES_DESKTOP",
            "MATLENS_WEB_DIST",
            "HERMES_WEB_DIST",
            "MATLENS_DESKTOP_READY_FILE",
            "HERMES_DESKTOP_READY_FILE",
            "MATLENS_HOME",
            "HERMES_HOME",
        ],
    )
    def test_desktop_writes_variable(self, main_ts, variable):
        assert variable in main_ts, f"desktop must still pass {variable}"

    def test_desktop_sends_both_session_header_names(self, main_ts):
        assert "'X-MatLens-Session-Token': token" in main_ts
        assert "'X-Hermes-Session-Token': token" in main_ts

    def test_desktop_resolves_home_from_matlens_env_first(self, main_ts):
        assert "process.env.MATLENS_HOME" in main_ts
        assert "resolveMatLensHome" in main_ts


class TestModulePlacement:
    """The compat layer must stay importable *before* any install repair.

    A top-level module (``matlens_env_compat`` at the repo root) only
    resolves through the editable-install finder, whose module map is baked
    at install time. A user who pulled the rename and ran the CLI before
    re-installing would hit ``ModuleNotFoundError`` on a startup import —
    and because ``matlens_bootstrap`` is imported first by every entry
    point, the CLI would fail to boot entirely, leaving the user unable to
    run ``matlens update`` to repair the install.

    Inside the ``matlens_cli`` package the file is found the moment it
    lands on disk, so no re-install is required.
    """

    def test_compat_module_lives_inside_the_package(self):
        import matlens_cli.env_compat as env_compat

        assert env_compat.__name__ == "matlens_cli.env_compat"
        assert "matlens_cli" in env_compat.__file__

    def test_compat_module_is_not_declared_as_a_top_level_module(self):
        """A stray top-level declaration would resurrect the stale-install bug."""
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        assert '"matlens_env_compat"' not in pyproject

    def test_no_source_file_imports_the_top_level_path(self):
        """No module may import ``matlens_env_compat`` directly any more."""
        offenders = []
        for path in REPO_ROOT.rglob("*.py"):
            relative = path.relative_to(REPO_ROOT)
            if relative.parts[0] in {".venv", "vendor", "_archive", "_backup_config"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(("import matlens_env_compat", "from matlens_env_compat")):
                    offenders.append(f"{relative}: {stripped}")

        assert not offenders, f"top-level imports found: {offenders}"


class TestBootstrapStaysDependencyFree:
    """``matlens_bootstrap`` must not drag in any project package.

    It is imported *before* anything else by every entry point, including
    ``tui_gateway/entry.py`` and ``tui_gateway/slash_worker.py``, which
    import it unguarded. Any intra-project import here would make the
    bootstrap fail exactly when the install is half-broken.
    """

    def test_bootstrap_imports_no_project_module(self):
        """Only *module-level* imports are checked.

        A function-local import is a deliberate lazy load (the bootstrap
        pulls in ``tools.lazy_deps`` inside a try/except so the heavy
        dependency never loads on the happy path), and is fine.
        """
        text = (REPO_ROOT / "matlens_bootstrap.py").read_text(encoding="utf-8")
        tree = ast.parse(text)

        stdlib = set(sys.stdlib_module_names)

        top_level_imports = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                top_level_imports.append(node.module or "")

        offenders = [
            name for name in top_level_imports if name.split(".")[0] not in stdlib
        ]
        assert not offenders, (
            f"matlens_bootstrap must not import {offenders!r} at module level — "
            f"it is imported before the install is guaranteed to be sound"
        )

    def test_bootstrap_reads_both_lazy_target_spellings(self):
        """The bootstrap and ``tools.lazy_deps`` must agree on both names."""
        bootstrap_text = (REPO_ROOT / "matlens_bootstrap.py").read_text(encoding="utf-8")
        lazy_text = (REPO_ROOT / "tools" / "lazy_deps.py").read_text(encoding="utf-8")

        for spelling in ("MATLENS_LAZY_INSTALL_TARGET", "HERMES_LAZY_INSTALL_TARGET"):
            assert spelling in bootstrap_text
            assert spelling in lazy_text
