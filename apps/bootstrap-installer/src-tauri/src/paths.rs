//! Filesystem paths + logging setup.
//!
//! Mirrors `matlens_constants.get_matlens_home()` from the Python CLI and
//! `resolveMatLensHome()` from the Electron desktop:
//!   Windows: %USERPROFILE%\.matlens
//!   macOS:   ~/.matlens
//!   Linux:   ~/.matlens
//!
//! Override via $MATLENS_HOME (canonical) or $HERMES_HOME (pre-rename name).
//!
//! NOTE (macOS): Python's get_matlens_home(), scripts/install.sh, and the
//! Electron desktop's resolveMatLensHome() ALL use ~/.matlens on macOS — there
//! is no ~/Library/Application Support branch anywhere else. An earlier
//! version of this file used Application Support, which drifted from every
//! other component: the installer wrote the install to one dir and the
//! desktop looked for it in another, so first launch never found the backend.
//!
//! IMPORTANT: this must match exactly. Drift here means install.ps1
//! writes to one place and the installer reads from another, breaking
//! the bootstrap-complete check.

use std::path::{Path, PathBuf};
#[cfg(target_os = "macos")]
use std::process::Command;
use tracing_appender::non_blocking::WorkerGuard;

/// Returns the canonical MatLens home directory.
///
/// Resolution order — mirrors the Electron desktop's `resolveMatLensHome()`
/// and the Python `matlens_constants.get_matlens_home()`:
///
///   1. `$MATLENS_HOME`        (canonical)
///   2. `$HERMES_HOME`         (pre-rename name, still honoured)
///   3. a pre-rename tree that actually exists (`~/.hermes`,
///      `%LOCALAPPDATA%\hermes`)
///   4. the canonical default `~/.matlens`
///
/// Step 3 is what keeps pre-rename installs working: an existing legacy tree
/// wins over the canonical default, so the rename never strands a user's
/// config, memories or sessions.
///
/// The default is `~/.matlens` on EVERY platform, Windows included. The
/// Python backend deliberately moved away from `%LOCALAPPDATA%\matlens`
/// (30+ call sites hard-code `~/.matlens`), and `scripts/install.ps1` /
/// `scripts/install.sh` / the Electron desktop all agree on `~/.matlens` —
/// a Windows-only `%LOCALAPPDATA%` default here would put the installer on a
/// third tree that nothing else reads.
pub fn hermes_home() -> PathBuf {
    if let Ok(override_path) = std::env::var("MATLENS_HOME") {
        if !override_path.trim().is_empty() {
            return PathBuf::from(override_path);
        }
    }

    if let Ok(legacy_path) = std::env::var("HERMES_HOME") {
        if !legacy_path.trim().is_empty() {
            return PathBuf::from(legacy_path);
        }
    }

    let canonical = default_home_root();

    if canonical.exists() {
        return canonical;
    }

    for legacy in legacy_home_roots() {
        if legacy.exists() {
            return legacy;
        }
    }

    canonical
}

/// The canonical default home root — `~/.matlens` on every platform.
fn default_home_root() -> PathBuf {
    if let Some(home) = dirs::home_dir() {
        return home.join(".matlens");
    }

    // Last resort — current dir, almost certainly wrong but at least
    // doesn't panic.
    PathBuf::from(".matlens")
}

/// Pre-rename home roots, checked only when the canonical one is absent.
fn legacy_home_roots() -> Vec<PathBuf> {
    let mut roots: Vec<PathBuf> = Vec::new();

    // Where this installer used to install on Windows.
    #[cfg(target_os = "windows")]
    if let Some(local_app_data) = dirs::data_local_dir() {
        roots.push(local_app_data.join("hermes"));
    }

    // Where it used to install on macOS / Linux, and where the Python
    // backend's pre-rename default pointed.
    if let Some(home) = dirs::home_dir() {
        roots.push(home.join(".hermes"));
    }

    roots
}

/// The install directory inside the given home root.
///
/// A fresh install lands in `matlens-agent`; a pre-rename install lives in
/// `hermes-agent`. Prefer the canonical name but fall back to the legacy one
/// when only the legacy one exists, so an existing install keeps working —
/// the same "prefer canonical, accept legacy" rule the Electron desktop
/// applies to `ACTIVE_HERMES_ROOT`.
pub fn install_root_in(home: &Path) -> PathBuf {
    let canonical = home.join("matlens-agent");

    if canonical.exists() {
        return canonical;
    }

    let legacy = home.join("hermes-agent");

    if legacy.exists() {
        return legacy;
    }

    canonical
}

/// The install directory inside the resolved home root.
pub fn active_install_root() -> PathBuf {
    install_root_in(&hermes_home())
}

pub fn log_dir() -> PathBuf {
    hermes_home().join("logs")
}

pub fn log_path() -> PathBuf {
    log_dir().join("bootstrap-installer.log")
}

pub fn bootstrap_cache_dir() -> PathBuf {
    hermes_home().join("bootstrap-cache")
}

/// Stable location the installer copies itself to after a successful install.
/// The desktop app re-invokes this with `--update`, and the start-menu /
/// desktop shortcuts can point users back to it. Lives directly under the home
/// root so it survives repo checkout deletion (unlike anything under
/// `matlens-agent/`).
///
/// On Windows this is `%USERPROFILE%\.matlens\matlens-setup.exe`; on other
/// platforms the extension differs but the directory is the same. The name
/// matches what the Electron desktop looks for in
/// `resolveStagedUpdaterBinary()`.
pub fn installer_dest() -> PathBuf {
    let name = if cfg!(target_os = "windows") {
        "matlens-setup.exe"
    } else {
        "matlens-setup"
    };
    hermes_home().join(name)
}

/// Canonical name of the update-in-progress marker, shared with the Python
/// CLI (`matlens_cli/update_lock.py`) and the Electron desktop
/// (`apps/desktop/electron/update-marker.ts`).
pub const UPDATE_MARKER_NAME: &str = ".matlens-update-in-progress";

/// Pre-rename name of the update-in-progress marker. Still honoured on read:
/// a marker written by a pre-rename updater or desktop must keep blocking a
/// second updater, otherwise two updaters mutate one checkout at once.
pub const LEGACY_UPDATE_MARKER_NAME: &str = ".hermes-update-in-progress";

/// Marker the updater writes for the duration of an in-app update and removes
/// when it finishes (see update.rs `UpdateMarkerGuard`). A freshly-launched
/// desktop checks this before spawning its own local backend: spawning one
/// mid-update re-locks the venv shim and triggers `force_kill_other_matlens`,
/// which then kills that legitimate backend in a respawn loop (#50238).
///
/// Lives directly under the home root (same rationale as `installer_dest`) so
/// the Electron desktop — which resolves the home root identically and pins it
/// into the updater's env — agrees on the exact path.
///
/// The name is the canonical `.matlens-update-in-progress`, matching the
/// desktop's `markerPath()`. A pre-rename marker under the legacy name is
/// still *read* (see `legacy_update_in_progress_marker`) so an update started
/// by an older installer keeps gating launches.
pub fn update_in_progress_marker() -> PathBuf {
    hermes_home().join(UPDATE_MARKER_NAME)
}

/// Copy the currently-running installer binary to `installer_dest()` so it's
/// available for future `--update` runs and shortcut launches.
///
/// No-ops (returns Ok) when the running exe is ALREADY the destination — which
/// is exactly the case during an `--update` run (the desktop launched us FROM
/// that path), where copying onto ourselves would be a Windows sharing
/// violation. Best-effort: a failure here must not fail the install, so the
/// caller logs and continues.
///
/// NOTE: because of that no-op, a user's staged installer is only ever written
/// by a full install/repair. Every later `--update` runs the ORIGINAL binary,
/// so an installer-protocol change can strand the whole installed base on a
/// binary that predates it (see `restage_from_checkout`, which repairs this
/// from the freshly-updated checkout).
pub fn copy_self_to_hermes_home() -> std::io::Result<()> {
    let src = std::env::current_exe()?;
    let dest = installer_dest();

    // Skip if we're already running from the destination (update re-invocation
    // or a prior copy). canonicalize both so symlinks / 8.3 short paths / case
    // differences don't trick us into a self-copy.
    let same = match (src.canonicalize(), dest.canonicalize()) {
        (Ok(a), Ok(b)) => a == b,
        _ => src == dest,
    };
    if same {
        tracing::info!(?dest, "installer already at destination; skipping self-copy");
        return Ok(());
    }

    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::copy(&src, &dest)?;
    repair_macos_installer_helper(&dest);
    tracing::info!(?src, ?dest, "copied installer to the MatLens home root");
    Ok(())
}

#[cfg(target_os = "macos")]
fn repair_macos_installer_helper(path: &Path) {
    // The staged helper may inherit quarantine from the downloaded installer.
    // Desktop later launches this exact file for in-app updates, so make it
    // executable before the update handoff reaches LaunchServices/Gatekeeper.
    let _ = Command::new("/usr/bin/xattr")
        .args(["-cr"])
        .arg(path)
        .status();

    let verify = Command::new("/usr/bin/codesign")
        .arg("--verify")
        .arg(path)
        .status();

    if !matches!(verify, Ok(status) if status.success()) {
        let _ = Command::new("/usr/bin/codesign")
            .args(["--force", "--sign", "-"])
            .arg(path)
            .status();
    }
}

#[cfg(not(target_os = "macos"))]
fn repair_macos_installer_helper(_path: &Path) {}

/// Where the bootstrap-complete marker lives (existence-only for the Rust
/// installer fast path; JSON schema-checked by the Electron app). Per main.ts:
///   const BOOTSTRAP_COMPLETE_MARKER = path.join(ACTIVE_HERMES_ROOT, '.matlens-bootstrap-complete')
/// We don't always know ACTIVE_HERMES_ROOT until install.ps1 reports it, so
/// this is a probe helper, not a definitive path.
pub fn likely_bootstrap_marker(install_root: &Path) -> PathBuf {
    install_root.join(".matlens-bootstrap-complete")
}

/// Legacy name of the bootstrap-complete marker, written by pre-rename builds
/// of install.ps1, install.sh and this installer.
pub fn legacy_bootstrap_marker(install_root: &Path) -> PathBuf {
    install_root.join(".hermes-bootstrap-complete")
}

/// Whether a bootstrap-complete marker exists under `install_root` — canonical
/// name first, legacy name second.
///
/// The legacy name is honoured so a tree installed before the rename still
/// takes the "already installed" fast path. Without it every launch of a
/// pre-rename install would re-run the whole first-launch bootstrap.
pub fn bootstrap_marker_exists(install_root: &Path) -> bool {
    likely_bootstrap_marker(install_root).exists() || legacy_bootstrap_marker(install_root).exists()
}

/// Initializes tracing to bootstrap-installer.log under HERMES_HOME/logs/.
/// Returns a guard that flushes the appender on drop — keep it alive for
/// the lifetime of the process.
pub fn init_logging() -> Option<WorkerGuard> {
    let dir = log_dir();
    if let Err(err) = std::fs::create_dir_all(&dir) {
        // No log dir → log to stderr only. Don't panic; the installer
        // should still be usable on an exotic filesystem.
        eprintln!("[matlens-setup] could not create log dir {dir:?}: {err}");
        return None;
    }

    let file_appender = tracing_appender::rolling::never(&dir, "bootstrap-installer.log");
    let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);

    let env_filter = tracing_subscriber::EnvFilter::try_from_env("HERMES_BOOTSTRAP_LOG")
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));

    tracing_subscriber::fmt()
        .with_env_filter(env_filter)
        .with_writer(non_blocking)
        .with_ansi(false)
        .with_target(true)
        .init();

    Some(guard)
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn get_log_path() -> String {
    log_path().to_string_lossy().into_owned()
}

#[tauri::command]
pub fn get_hermes_home() -> String {
    hermes_home().to_string_lossy().into_owned()
}

#[tauri::command]
pub fn open_log_dir(app: tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let path = log_dir();
    app.opener()
        .open_path(path.to_string_lossy(), None::<&str>)
        .map_err(|e| e.to_string())
}
