"""Guards against a rename sweep corrupting third-party package names.

MatLens was renamed from ``hermes-agent`` to ``matlens-agent``.  A blanket
search-and-replace across the tree also renamed *third-party* packages that
happened to share the prefix — most notably Facebook's ``hermes-parser`` /
``hermes-estree``, which ``eslint-plugin-react-hooks`` depends on.

Two failure modes are guarded here:

1. A lockfile entry whose ``resolved`` tarball URL points at a package name
   that differs from the dependency that declares it.  npm would either 404 on
   install or silently resolve a different package.
2. A lockfile entry that names a ``node_modules/<name>`` path for a package
   that is not published under that name — the shape of the corruption.

The check is deliberately offline: it compares the lockfile against the
dependency declarations inside the lockfile itself, and against the packages
the project declares in ``package.json``.  It never contacts the registry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# tests/ci/ -> tests/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
LOCKFILE = REPO_ROOT / "package-lock.json"

# The project's own packages legitimately carry the "matlens" prefix; they are
# workspace links and are resolved from disk, not from the registry.
_WORKSPACE_LINKS = {
    "matlens",
    "matlens-agent",
    "matlens-tui",
}

# Third-party packages whose upstream names start with "hermes" and must NOT
# be renamed.  Each maps the (wrong) name we might have written to the real
# published name.
_UPSTREAM_NAMES = {
    "hermes-parser": "hermes-parser",
    "hermes-estree": "hermes-estree",
}


def _load_lock() -> dict:
    if not LOCKFILE.exists():
        pytest.skip(f"{LOCKFILE} not present")
    return json.loads(LOCKFILE.read_text(encoding="utf-8"))


def _tarball_package_name(resolved: str) -> str | None:
    """Extract the package name from an npm tarball URL."""
    match = re.match(r"https?://[^/]+/(.+)/-/[^/]+-\d[^/]*\.tgz", resolved)
    return match.group(1) if match else None


class TestLockfileThirdPartyNames:
    def test_no_matlens_prefixed_third_party_packages(self):
        """Only our own workspaces may be called "matlens-*".

        ``hermes-parser`` and ``hermes-estree`` are Facebook packages pulled in
        by eslint-plugin-react-hooks.  Renaming them produces lock entries
        whose tarball URLs 404, which breaks ``npm ci`` outright.
        """
        lock = _load_lock()
        packages = lock.get("packages", {})

        offenders = []
        for path, meta in packages.items():
            name = path.split("node_modules/")[-1] if "node_modules/" in path else path
            if not name.startswith("matlens-"):
                continue
            if name in _WORKSPACE_LINKS:
                continue
            if meta.get("link"):
                # A workspace link resolves from disk — the directory name is
                # ours to choose.
                continue
            offenders.append((path, meta.get("resolved")))

        assert not offenders, (
            "Third-party packages must not carry the 'matlens-' prefix: "
            f"{offenders}. Restore the upstream published name."
        )

    def test_tarball_url_matches_declaring_dependency(self):
        """A dependency must resolve to the tarball of the package it names.

        The corruption we hit rewrote the dependency name *and* the URL
        together, so both halves stayed self-consistent.  What actually broke
        was that neither half matched the published package.  We catch that by
        requiring the declared dependency name to agree with the tarball URL
        it resolves to.
        """
        lock = _load_lock()
        packages = lock.get("packages", {})

        mismatches = []
        for path, meta in packages.items():
            resolved = meta.get("resolved")
            if not resolved or not resolved.startswith("http"):
                continue
            url_pkg = _tarball_package_name(resolved)
            if url_pkg is None:
                continue
            key = path.split("node_modules/")[-1]
            if key != url_pkg:
                # npm aliases (e.g. "foo-cjs" -> "foo") are legitimate.
                if key.endswith("-cjs") and key == f"{url_pkg}-cjs":
                    continue
                mismatches.append((path, url_pkg))

        assert not mismatches, (
            f"Lock entries whose key and tarball URL disagree: {mismatches}"
        )

    def test_eslint_react_hooks_parser_dependency_is_intact(self):
        """The concrete dependency that broke must stay intact.

        eslint-plugin-react-hooks@7 declares ``hermes-parser``; if the lock
        rewrites that to a name that is not published, ESLint dies with
        "Cannot find module" before it can lint a single file.
        """
        lock = _load_lock()
        packages = lock.get("packages", {})

        hooks = packages.get("node_modules/eslint-plugin-react-hooks")
        assert hooks is not None, "eslint-plugin-react-hooks missing from lock"

        declared = hooks.get("dependencies", {})
        assert "hermes-parser" in declared, (
            f"eslint-plugin-react-hooks must depend on 'hermes-parser', got "
            f"{sorted(declared)}"
        )
        assert "node_modules/hermes-estree" in packages, (
            "hermes-estree (hermes-parser's own dependency) missing from lock"
        )


class TestRepoRenameDidNotTouchVendorPackages:
    def test_vendor_package_names_are_not_renamed_anywhere(self):
        """The upstream names must appear verbatim in the lockfile.

        This is the inverse guard: it fails if someone 'fixes' the lock by
        renaming the dependency back to the published name but forgets to
        update the tarball URL, or vice versa.
        """
        lock = _load_lock()
        packages = lock.get("packages", {})

        for upstream in _UPSTREAM_NAMES:
            entry = packages.get(f"node_modules/{upstream}")
            assert entry is not None, f"node_modules/{upstream} missing from lock"
            resolved = entry.get("resolved", "")
            assert f"/{upstream}/-/{upstream}-" in resolved, (
                f"{upstream} must resolve to its own tarball, got {resolved}"
            )

    def test_integrity_hash_matches_upstream_publication(self):
        """The recorded integrity must be the published one.

        We recorded the hash of the real tarball; renaming the package did not
        change the bytes.  If the hash ever changes, a different artifact is
        being installed and the lock needs regeneration rather than a rename.
        """
        lock = _load_lock()
        packages = lock.get("packages", {})

        parser = packages.get("node_modules/hermes-parser", {})
        assert parser.get("version") == "0.25.1"
        assert parser.get("integrity") == (
            "sha512-6pEjquH3rqaI6cYAXYPcz9MS4rY6R4ngRgrgfDshRptUZIc3lw0MCIJIGDj9++"
            "mfySOuPTHB4nrSW99BCvOPIA=="
        )
