"""Guards the on-disk contracts shared by the installer, the desktop and the CLI.

The Hermes → MatLens rename touched four independent implementations of the
same few names — the Python CLI, the Electron desktop, the Tauri bootstrap
installer and the POSIX/PowerShell install scripts.  They only agree by
convention, and nothing in the type system or the test suite enforces it: a
rename applied to one side and not the other produces code that compiles,
passes its own unit tests, and then fails at runtime.

The break this file exists to prevent, found during the batch-0 rename audit:

* ``matlens_cli/update_lock.py`` reads the hand-off pid from
  ``MATLENS_UPDATE_HANDOFF_PID``; the Rust installer exported
  ``HERMES_UPDATE_HANDOFF_PID``.  The child never saw its parent's claim, so
  every GUI update refused its own parent's lock and dead-ended on exit 2 —
  with no error pointing at the rename.
* The Rust installer staged itself as ``hermes-setup.exe`` while the desktop
  looked for ``matlens-setup.exe``, so the in-app update hand-off silently
  degraded.
* ``scripts/install.sh`` stamped ``.matlens-bootstrap-complete`` while
  ``scripts/install.ps1`` stamped ``.hermes-bootstrap-complete`` and the
  desktop read a third name — so on macOS/Linux the desktop never saw the
  marker's own install and re-ran the whole first-launch bootstrap on every
  launch.

Each check below pins one name to the single canonical spelling, and (where a
legacy spelling must keep working) pins the fallback rule instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# tests/ci/ -> tests/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

RUST_SRC = REPO_ROOT / "apps" / "bootstrap-installer" / "src-tauri" / "src"
DESKTOP_ELECTRON = REPO_ROOT / "apps" / "desktop" / "electron"

# --- the canonical names ---------------------------------------------------

#: The update-in-progress marker, shared by the Python CLI, the Electron
#: desktop and the Rust installer.
CANONICAL_UPDATE_MARKER = ".matlens-update-in-progress"

#: The pre-rename spelling, still honoured on read.
LEGACY_UPDATE_MARKER = ".hermes-update-in-progress"

#: The bootstrap-complete marker, shared by both install scripts, the Rust
#: installer and the Electron desktop.
CANONICAL_BOOTSTRAP_MARKER = ".matlens-bootstrap-complete"

#: The pre-rename spelling, still honoured on read.
LEGACY_BOOTSTRAP_MARKER = ".hermes-bootstrap-complete"

#: The environment variable the Rust updater exports so the Python
#: ``matlens update`` child recognises the live holder as its own parent.
CANONICAL_HANDOFF_PID_ENV = "MATLENS_UPDATE_HANDOFF_PID"

#: The staged installer binary the desktop hands updates to.
CANONICAL_STAGED_INSTALLER = "matlens-setup.exe"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def _rust(name: str) -> str:
    return _read(RUST_SRC / name)


def _desktop(name: str) -> str:
    return _read(DESKTOP_ELECTRON / name)


class TestUpdateMarkerName:
    """The three implementations must name the update marker identically."""

    def test_python_cli_uses_the_canonical_marker_name(self) -> None:
        source = _read(REPO_ROOT / "matlens_cli" / "update_lock.py")
        assert f'MARKER_NAME = "{CANONICAL_UPDATE_MARKER}"' in source

    def test_desktop_uses_the_canonical_marker_name(self) -> None:
        source = _desktop("update-marker.ts")
        assert f"'{CANONICAL_UPDATE_MARKER}'" in source

    def test_rust_installer_uses_the_canonical_marker_name(self) -> None:
        source = _rust("paths.rs")
        assert f'"{CANONICAL_UPDATE_MARKER}"' in source

    def test_legacy_marker_is_still_read_by_the_desktop(self) -> None:
        # A pre-rename installer still writes the legacy name; ignoring it
        # would let the desktop spawn a backend mid-update.
        source = _desktop("update-marker.ts")
        assert f"'{LEGACY_UPDATE_MARKER}'" in source

    def test_legacy_marker_is_still_read_by_the_rust_installer(self) -> None:
        # The legacy name lives in paths.rs as the single shared constant the
        # updater's guard consults.
        source = _rust("paths.rs")
        assert f'LEGACY_UPDATE_MARKER_NAME: &str = "{LEGACY_UPDATE_MARKER}"' in source
        assert "LEGACY_UPDATE_MARKER_NAME" in _rust("update.rs")


class TestHandoffPidEnv:
    """The Rust updater must export the variable the Python child reads.

    This is the contract that silently broke the in-app update: the two sides
    used different spellings, so the child never recognised its parent and
    refused the lock with exit 2.
    """

    def test_python_cli_declares_the_canonical_env_name(self) -> None:
        source = _read(REPO_ROOT / "matlens_cli" / "update_lock.py")
        assert f'HANDOFF_PID_ENV = "{CANONICAL_HANDOFF_PID_ENV}"' in source

    def test_rust_exports_the_same_env_name_the_python_reads(self) -> None:
        source = _rust("update.rs")
        assert f'"{CANONICAL_HANDOFF_PID_ENV}"' in source

    def test_rust_also_exports_the_legacy_name(self) -> None:
        # A `matlens update` child that predates the rename still reads the
        # legacy spelling, so both are exported.
        source = _rust("update.rs")
        assert '"HERMES_UPDATE_HANDOFF_PID"' in source


class TestBootstrapMarkerName:
    """Both install scripts, the Rust installer and the desktop must agree."""

    def test_install_sh_stamps_the_canonical_marker(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "install.sh")
        assert CANONICAL_BOOTSTRAP_MARKER in source
        # The legacy spelling must not be the one we publish any more.
        publish_lines = [
            line
            for line in source.splitlines()
            if "bootstrap-complete" in line and "marker_path" in line
        ]
        assert publish_lines, "install.sh must publish a bootstrap marker"
        assert all(CANONICAL_BOOTSTRAP_MARKER in line for line in publish_lines)

    def test_install_ps1_stamps_the_canonical_marker(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "install.ps1")
        assert f'"{CANONICAL_BOOTSTRAP_MARKER}"' in source

    def test_rust_installer_stamps_the_canonical_marker(self) -> None:
        source = _rust("paths.rs")
        assert f'"{CANONICAL_BOOTSTRAP_MARKER}"' in source

    def test_desktop_reads_the_canonical_marker(self) -> None:
        source = _desktop("main.ts")
        assert f"'{CANONICAL_BOOTSTRAP_MARKER}'" in source

    def test_desktop_still_reads_the_legacy_marker(self) -> None:
        # A tree installed before the rename carries only the legacy file;
        # treating it as "never bootstrapped" re-runs the whole first-launch
        # flow on every launch.
        source = _desktop("main.ts")
        assert f"'{LEGACY_BOOTSTRAP_MARKER}'" in source


class TestStagedInstallerName:
    """The installer stages itself under the name the desktop looks for."""

    def test_rust_stages_the_canonical_binary_name(self) -> None:
        source = _rust("paths.rs")
        assert f'"{CANONICAL_STAGED_INSTALLER}"' in source

    def test_desktop_looks_for_the_canonical_binary_name(self) -> None:
        source = _desktop("updater-process.ts")
        assert f"'{CANONICAL_STAGED_INSTALLER}'" in source

    def test_desktop_still_finds_the_pre_rename_binary(self) -> None:
        source = _desktop("updater-process.ts")
        assert "'hermes-setup.exe'" in source


class TestLegacyCompatibility:
    """The legacy spellings must stay READABLE everywhere.

    A staged installer binary is only refreshed by a full installer run, so a
    user can easily drive a NEW checkout with an OLD staged updater. That old
    updater claims the legacy marker and exports the legacy hand-off variable
    — if nobody reads them any more, the child refuses its own parent's lock
    and the GUI update dead-ends on exit 2, exactly as it did before the
    rename.
    """

    def test_python_reads_the_legacy_marker_name(self) -> None:
        source = _read(REPO_ROOT / "matlens_cli" / "update_lock.py")
        assert f'LEGACY_MARKER_NAME = "{LEGACY_UPDATE_MARKER}"' in source

    def test_python_reads_the_legacy_handoff_env_name(self) -> None:
        source = _read(REPO_ROOT / "matlens_cli" / "update_lock.py")
        assert f'LEGACY_HANDOFF_PID_ENV = "HERMES_UPDATE_HANDOFF_PID"' in source

    def test_rust_reads_the_legacy_marker_name(self) -> None:
        source = _rust("update.rs")
        assert "LEGACY_UPDATE_MARKER_NAME" in source

    def test_desktop_reads_the_legacy_marker_name(self) -> None:
        source = _desktop("update-marker.ts")
        assert f"'{LEGACY_UPDATE_MARKER}'" in source


class TestRustBuildIntegrity:
    """Rename damage that breaks the crate build itself.

    Both of these were found by ``cargo check``: the manifest file was renamed
    but ``include_str!`` still pointed at the old name, and the lib target was
    renamed while ``main.rs`` still called the old one. Neither shows up in a
    grep for "hermes" — the build simply fails.
    """

    def test_build_script_includes_the_manifest_that_exists(self) -> None:
        build_rs = _read(RUST_SRC.parent / "build.rs")
        included = re.findall(r'include_str!\("([^"]+)"\)', build_rs)
        assert included, "build.rs must include the windows manifest"
        for name in included:
            assert (RUST_SRC.parent / name).is_file(), (
                f"build.rs includes {name!r}, which does not exist — the crate "
                f"cannot build"
            )

    def test_main_calls_the_library_target_cargo_declares(self) -> None:
        cargo_toml = _read(RUST_SRC.parent / "Cargo.toml")
        declared = re.search(r'^\[lib\]\s*\nname\s*=\s*"([^"]+)"', cargo_toml, re.MULTILINE)
        assert declared, "Cargo.toml must declare a [lib] target"
        lib_name = declared.group(1)

        main_rs = _read(RUST_SRC / "main.rs")
        assert f"{lib_name}::run()" in main_rs, (
            f"main.rs must call the declared lib target {lib_name!r}"
        )


class TestHomeRootAgreement:
    """The installer and the desktop must resolve the SAME home root.

    The Rust installer used to default to ``%LOCALAPPDATA%\\hermes`` on
    Windows while the Python CLI, both install scripts and the desktop all
    used ``~/.matlens`` — three trees on one machine.
    """

    def test_rust_reads_the_canonical_home_env_first(self) -> None:
        source = _rust("paths.rs")
        canonical_at = source.find('std::env::var("MATLENS_HOME")')
        legacy_at = source.find('std::env::var("HERMES_HOME")')
        assert canonical_at != -1, "the Rust installer must read $MATLENS_HOME"
        assert legacy_at != -1, "the Rust installer must still read $HERMES_HOME"
        assert canonical_at < legacy_at, "the canonical name must win"

    def test_rust_default_home_root_is_dot_matlens(self) -> None:
        source = _rust("paths.rs")
        assert 'home.join(".matlens")' in source
        # The Windows-only %LOCALAPPDATA% default is gone: it pointed at a
        # tree no other component reads.
        assert 'data_local_dir()' in source  # legacy candidate only
        assert 'local_app_data.join("hermes")' in source

    def test_python_cli_default_home_is_dot_matlens(self) -> None:
        source = _read(REPO_ROOT / "matlens_constants.py")
        assert 'Path.home() / ".matlens"' in source

    def test_install_scripts_use_the_canonical_home_default(self) -> None:
        sh = _read(REPO_ROOT / "scripts" / "install.sh")
        assert '$HOME/.matlens' in sh
        ps1 = _read(REPO_ROOT / "scripts" / "install.ps1")
        assert "$env:USERPROFILE\\.matlens" in ps1


class TestInstallRootAgreement:
    """``matlens-agent`` for a fresh install, ``hermes-agent`` for a legacy one."""

    def test_rust_prefers_the_canonical_install_dir(self) -> None:
        source = _rust("paths.rs")
        assert 'home.join("matlens-agent")' in source
        assert 'home.join("hermes-agent")' in source
        canonical_at = source.find('home.join("matlens-agent")')
        legacy_at = source.find('home.join("hermes-agent")')
        assert canonical_at < legacy_at, "the canonical install dir must be preferred"

    def test_install_scripts_use_the_canonical_install_dir(self) -> None:
        sh = _read(REPO_ROOT / "scripts" / "install.sh")
        assert "$MATLENS_HOME/matlens-agent" in sh
        ps1 = _read(REPO_ROOT / "scripts" / "install.ps1")
        assert "\\matlens-agent" in ps1


@pytest.mark.parametrize(
    "relative_path",
    [
        "apps/bootstrap-installer/src-tauri/src/paths.rs",
        "apps/bootstrap-installer/src-tauri/src/update.rs",
        "apps/bootstrap-installer/src-tauri/src/bootstrap.rs",
    ],
)
def test_rust_sources_do_not_hardcode_the_legacy_home_default(relative_path: str) -> None:
    """``~/.hermes`` / ``%LOCALAPPDATA%\\hermes`` must not be a *default*.

    They stay legal as a legacy *candidate* (an existing tree is honoured),
    but no component may resolve to one by default — that is what put the
    installer on a tree nothing else reads.
    """
    source = _read(REPO_ROOT / relative_path)
    if "home.join(\".hermes\")" not in source:
        pytest.skip("no legacy home candidate in this file")

    # The legacy join must live inside the legacy-candidate helper, never in
    # the function that computes the default root.
    legacy_fn = source.find("fn legacy_home_roots()")
    default_fn = source.find("fn default_home_root()")
    assert legacy_fn != -1, "a legacy candidate must live in legacy_home_roots()"
    assert default_fn != -1, "the default root must be computed by default_home_root()"

    legacy_join = source.find('home.join(".hermes")')
    assert legacy_join > legacy_fn, "the legacy join belongs to legacy_home_roots()"

    default_block = source[default_fn:legacy_fn]
    assert 'home.join(".matlens")' in default_block, (
        "default_home_root() must resolve to ~/.matlens, not a legacy tree"
    )
    assert 'home.join(".hermes")' not in default_block


class TestLegacyHomeResolutionAgreement:
    """Five implementations resolve the home root; they must agree exactly.

    The Python CLI, the Rust installer, the Electron desktop and both install
    scripts each resolve "where does this user's data live" on their own.
    A pre-rename user has that data under ``~/.hermes`` (or the old
    ``%LOCALAPPDATA%\\hermes``), so all five must fall back to the legacy
    tree — otherwise the installer writes to one tree while the backend reads
    from another and the user's config appears to have vanished.

    The subtle rule that is easiest to get wrong: ``HERMES_HOME`` is honoured
    **only when its directory exists**.  Unlike ``MATLENS_HOME`` the user
    never chose that value — it is a leftover that may point at a deleted
    tree — so trusting it blindly relocates the user's data.
    """

    def test_python_reads_the_legacy_env_name(self) -> None:
        source = _read(REPO_ROOT / "matlens_constants.py")
        assert 'os.environ.get("HERMES_HOME"' in source, (
            "the Python backend must still read the pre-rename $HERMES_HOME"
        )

    def test_python_guards_the_legacy_env_with_an_existence_check(self) -> None:
        source = _read(REPO_ROOT / "matlens_constants.py")
        legacy_at = source.find('os.environ.get("HERMES_HOME"')
        assert legacy_at != -1
        window = source[legacy_at : legacy_at + 600]
        assert "_path_exists(legacy_env)" in window, (
            "$HERMES_HOME must only be honoured when its directory exists — "
            "a stale `setx HERMES_HOME` would otherwise relocate the user's "
            "config, memories and sessions"
        )

    def test_rust_guards_the_legacy_env_with_an_existence_check(self) -> None:
        source = _rust("paths.rs")
        legacy_at = source.find('std::env::var("HERMES_HOME")')
        assert legacy_at != -1, "the Rust installer must still read $HERMES_HOME"
        window = source[legacy_at : legacy_at + 700]
        assert ".exists()" in window, (
            "$HERMES_HOME must only be honoured when its directory exists"
        )

    def test_electron_guards_the_legacy_env_with_an_existence_check(self) -> None:
        source = _read(REPO_ROOT / "apps" / "desktop" / "electron" / "main.ts")
        legacy_at = source.find("process.env.HERMES_HOME")
        assert legacy_at != -1, "the desktop must still read $HERMES_HOME"
        window = source[legacy_at : legacy_at + 300]
        assert "directoryExists" in window, (
            "$HERMES_HOME must only be honoured when its directory exists"
        )

    def test_install_sh_guards_the_legacy_env_with_an_existence_check(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "install.sh")
        legacy_at = source.find('${HERMES_HOME:-')
        assert legacy_at != -1, "install.sh must still read $HERMES_HOME"
        window = source[legacy_at : legacy_at + 400]
        assert '[ -d "$HERMES_HOME" ]' in window, (
            "$HERMES_HOME must only be honoured when its directory exists"
        )

    def test_install_ps1_guards_the_legacy_env_with_an_existence_check(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "install.ps1")
        assert "$env:HERMES_HOME -and (Test-Path -LiteralPath $env:HERMES_HOME" in source, (
            "$HERMES_HOME must only be honoured when its directory exists"
        )

    def test_every_component_knows_the_pre_rename_home_root(self) -> None:
        """The legacy *directory* fallback has to exist on all four sides.

        A user who never set an env var at all still has their data in
        ``~/.hermes``; that path must be reachable everywhere.
        """
        assert ".hermes" in _read(REPO_ROOT / "matlens_constants.py")
        assert 'home.join(".hermes")' in _rust("paths.rs")
        assert "'.hermes'" in _read(REPO_ROOT / "apps" / "desktop" / "electron" / "main.ts")
        assert '"$HOME/.hermes"' in _read(REPO_ROOT / "scripts" / "install.sh")
        assert '"$env:USERPROFILE\\.hermes"' in _read(REPO_ROOT / "scripts" / "install.ps1")

    def test_canonical_home_is_preferred_over_the_legacy_root(self) -> None:
        """When both trees exist the canonical one wins, on every side."""
        python_source = _read(REPO_ROOT / "matlens_constants.py")
        canonical_at = python_source.find("if _path_exists(canonical):")
        legacy_at = python_source.find("for legacy in _legacy_matlens_home_roots():")
        assert canonical_at != -1 and legacy_at != -1
        assert canonical_at < legacy_at, (
            "the canonical home must be preferred over the pre-rename root"
        )

        rust_source = _rust("paths.rs")
        rust_canonical = rust_source.find("if canonical.exists()")
        rust_legacy = rust_source.find("for legacy in legacy_home_roots()")
        assert rust_canonical != -1 and rust_legacy != -1
        assert rust_canonical < rust_legacy

        electron_source = _read(REPO_ROOT / "apps" / "desktop" / "electron" / "main.ts")
        electron_canonical = electron_source.find(
            "if (!directoryExists(canonicalHome) && directoryExists(localappdataLegacy))"
        )
        assert electron_canonical != -1, (
            "the desktop must prefer the canonical home over the legacy root"
        )


# ---------------------------------------------------------------------------
# The CLI entry-point name.
#
# The break this section prevents, found in the batch-1 rename audit:
#
# ``pyproject.toml`` declares the console scripts as ``matlens`` /
# ``matlens-agent`` / ``matlens-acp``.  Nothing ever produced a ``hermes``
# or ``hermes.exe``.  Four components nevertheless looked for the name that
# does not exist:
#
# * ``scripts/install.ps1`` copied ``hermes.exe`` / ``hermes-acp.exe`` out of
#   the venv into the PATH directory — neither file exists, so the copy loop
#   silently copied nothing and the machine ended up with **no ``matlens``
#   command on PATH at all**.
# * ``scripts/install.ps1`` ran ``python -m hermes_cli.main setup`` — there is
#   no ``hermes_cli`` package (it is ``matlens_cli``), so the setup wizard
#   died with ModuleNotFoundError.
# * ``scripts/install.ps1`` ran ``py_compile`` on
#   ``$InstallDir/hermes_cli/web_server.py`` — a path that does not exist, so
#   the syntax check failed and the script **threw, aborting the install**.
# * ``scripts/desktop-update/windows.ps1`` drove the update through
#   ``python -m hermes_cli.main update`` — same missing module, so the whole
#   desktop update path failed.
#
# None of these fail at compile time. They fail on a user's machine, mid-
# install. This section pins the entry-point name to the one spelling that
# actually exists, and pins the legacy fallback where one is still needed.
# ---------------------------------------------------------------------------

#: The console script declared in pyproject.toml's ``[project.scripts]``.
CANONICAL_CLI_ENTRY = "matlens"

#: The Python module that actually implements the CLI.
CANONICAL_CLI_MODULE = "matlens_cli.main"


class TestCliEntryPointName:
    """Every component must invoke the CLI that actually exists."""

    def test_pyproject_declares_the_canonical_entry_point(self) -> None:
        source = _read(REPO_ROOT / "pyproject.toml")
        assert f'{CANONICAL_CLI_ENTRY} = "{CANONICAL_CLI_MODULE}:main"' in source

    def test_the_legacy_module_package_does_not_exist(self) -> None:
        # Guards the premise of every check below: if a `hermes_cli` package
        # ever comes back, these assertions would be pinning the wrong name.
        assert not (REPO_ROOT / "hermes_cli").exists()

    def test_install_ps1_does_not_invoke_the_missing_module(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "install.ps1")
        assert "hermes_cli.main" not in source
        assert f'-m {CANONICAL_CLI_MODULE}' in source

    def test_install_ps1_compiles_the_real_web_server_path(self) -> None:
        # The syntax check aborted the whole install when it targeted a path
        # that does not exist.
        source = _read(REPO_ROOT / "scripts" / "install.ps1")
        assert "hermes_cli/web_server.py" not in source
        assert "matlens_cli/web_server.py" in source

    def test_install_ps1_copies_the_launchers_that_exist(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "install.ps1")
        launcher_block = source.split("foreach ($launcher in", 1)[1].split(")", 1)[0]
        assert f'"{CANONICAL_CLI_ENTRY}.exe"' in launcher_block

    def test_desktop_update_script_does_not_invoke_the_missing_module(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "desktop-update" / "windows.ps1")
        assert "hermes_cli.main" not in source
        assert f'"{CANONICAL_CLI_MODULE}"' in source

    def test_posix_update_script_does_not_invoke_the_missing_module(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "desktop-update" / "posix.sh")
        assert "hermes_cli.main" not in source

    def test_install_sh_does_not_invoke_the_missing_module(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "install.sh")
        assert "hermes_cli.main" not in source
        assert f'-m {CANONICAL_CLI_MODULE}' in source


class TestVenvShimProbing:
    """The update-lock probe must cover the shim that actually exists.

    The venv shim is the file a running backend holds open on Windows. The
    lock guard is meaningless unless it probes the file that is really there.
    """

    def test_desktop_probes_the_canonical_shim(self) -> None:
        source = _desktop("main.ts")
        assert "'matlens.exe'" in source
        assert "'hermes.exe'" in source

    def test_desktop_no_longer_probes_only_the_legacy_shim(self) -> None:
        source = _desktop("main.ts")
        assert "venvHermesShimPath" not in source

    def test_rust_probes_both_shim_names(self) -> None:
        source = _rust("update.rs")
        assert '"matlens.exe"' in source
        assert '"hermes.exe"' in source
        assert "venv_hermes" not in source

    def test_windows_update_script_probes_both_shim_names(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "desktop-update" / "windows.ps1")
        assert "matlens.exe" in source
        assert "hermes.exe" in source


class TestProductIdentity:
    """The packaged app carries the MatLens name; legacy artefacts still resolve.

    The product was renamed from Hermes to MatLens. The packaged executable
    is now ``MatLens.exe`` / ``MatLens.app``, but the updater must still find
    a tree that was built before the rename — otherwise an in-place update
    cannot locate the bundle it is supposed to replace.
    """

    def test_package_json_uses_the_canonical_product_name(self) -> None:
        source = _read(REPO_ROOT / "apps" / "desktop" / "package.json")
        assert '"productName": "MatLens"' in source
        assert '"executableName": "MatLens"' in source

    def test_package_json_app_id_is_canonical(self) -> None:
        source = _read(REPO_ROOT / "apps" / "desktop" / "package.json")
        assert '"appId": "com.matlens.agent"' in source

    def test_desktop_app_user_model_id_matches_the_app_id(self) -> None:
        # The AUMID must equal the appId, or Windows toasts silently no-op.
        source = _desktop("main.ts")
        assert "app.setAppUserModelId('com.matlens.agent')" in source

    def test_rust_resolver_finds_both_the_new_and_the_old_bundle(self) -> None:
        source = _rust("bootstrap.rs")
        assert '"MatLens.exe"' in source
        assert '"Hermes.exe"' in source
        assert '"mac/MatLens.app/Contents/MacOS"' in source
        assert '"mac/Hermes.app/Contents/MacOS"' in source

    def test_rust_lock_probe_covers_both_macos_bundles(self) -> None:
        source = _rust("update.rs")
        assert '"MatLens.app"' in source
        assert '"Hermes.app"' in source

    def test_tauri_installer_uses_the_canonical_identifier(self) -> None:
        source = _read(
            REPO_ROOT / "apps" / "bootstrap-installer" / "src-tauri" / "tauri.conf.json"
        )
        assert '"identifier": "com.matlens.agent.setup"' in source

    def test_tauri_binary_name_is_canonical(self) -> None:
        source = _read(
            REPO_ROOT / "apps" / "bootstrap-installer" / "src-tauri" / "Cargo.toml"
        )
        assert 'name = "MatLens-Setup"' in source


class TestUpdateMarkerIsWrittenUnderBothNames:
    """A pre-rename reader must still see the lock held by a current writer.

    The rename made the marker canonical-only on the write side. A Python or
    Rust reader that predates the rename only knows the legacy name, so it
    would treat a live update as lock-free and start a second one.
    """

    def test_posix_update_script_writes_both_names(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "desktop-update" / "posix.sh")
        assert 'LEGACY_MARKER="$MATLENS_HOME/.hermes-update-in-progress"' in source
        assert '> "$LEGACY_MARKER"' in source

    def test_windows_update_script_writes_both_names(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "desktop-update" / "windows.ps1")
        assert '$LegacyMarkerPath = Join-Path $HermesHome ".hermes-update-in-progress"' in source
        assert "WriteAllText($LegacyMarkerPath" in source

    def test_windows_update_script_cleans_both_names(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "desktop-update" / "windows.ps1")
        assert "foreach ($marker in @($MarkerPath, $LegacyMarkerPath))" in source

    def test_install_ps1_finds_the_renamed_desktop_executable(self) -> None:
        # The packaged exe is now `MatLens.exe`. The installer's post-build
        # sanity check used to look only for `Hermes.exe`, so it threw
        # "Desktop build completed but no ... was found" on EVERY build —
        # aborting the install right after it had already built the app.
        source = _read(REPO_ROOT / "scripts" / "install.ps1")
        assert "$desktopDir\\release\\win-unpacked\\MatLens.exe" in source
        assert "$desktopDir\\release\\win-unpacked\\Hermes.exe" in source

    def test_install_ps1_does_not_hardcode_the_legacy_desktop_exe_only(self) -> None:
        source = _read(REPO_ROOT / "scripts" / "install.ps1")
        assert "no MatLens.exe was found" in source

    def test_exe_identity_stamp_uses_the_current_product_name(self) -> None:
        # The rcedit stamp is what the user sees in Task Manager.
        source = _read(REPO_ROOT / "apps" / "desktop" / "scripts" / "set-exe-identity.mjs")
        assert "ProductName: 'MatLens'" in source
        assert "ProductName: 'Hermes'" not in source
