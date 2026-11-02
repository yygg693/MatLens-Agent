"""Environment-variable compatibility shims for the Hermes → MatLens rename.

The upstream project shipped every environment variable under a ``HERMES_``
prefix.  MatLens renamed them to ``MATLENS_``, but the rename was applied
independently on the Python side and the Electron side, so for a window of
time the two halves disagreed on the wire:

    desktop (main.ts)            backend (Python)
    --------------------------   --------------------------
    HERMES_DASHBOARD_SESSION_    MATLENS_DASHBOARD_SESSION_
    TOKEN                        TOKEN
    HERMES_DESKTOP               MATLENS_DESKTOP
    HERMES_WEB_DIST              MATLENS_WEB_DIST
    HERMES_DESKTOP_READY_FILE    MATLENS_DESKTOP_READY_FILE
    HERMES_DESKTOP_TERMINAL      MATLENS_DESKTOP_TERMINAL

A desktop build that sends the old names to a renamed backend loses the
session token (the backend ignores the header outright → 401 on every
gated endpoint), skips the cron ticker, and never finds the web bundle.

This module provides the single place that knows how to read *either* name.
Every backend read site goes through :func:`matlens_env` so the fallback
rule lives in one file instead of being duplicated (and eventually drifting)
across twenty call sites.

Two deliberate exclusions
--------------------------

``MATLENS_HOME`` is **not** covered by the generic fallback.  It is a
*path* variable, and the two halves historically disagreed about the path
itself: the backend defaulted to ``~/.matlens`` while the desktop defaulted
to ``~/.hermes`` / ``%LOCALAPPDATA%\\hermes``.  Blindly honouring the old
name would therefore point the backend at an *empty* directory and make the
user's config, memories and sessions appear to vanish.  Path resolution
lives in :func:`matlens_constants.get_matlens_home` instead, and the desktop
now resolves to the same directory the backend uses.

Everything else in this table is a *functional* variable — a flag, a token,
or a file location that is always written by the same process that reads
it — so falling back to the legacy name is safe.

Why this lives inside the ``matlens_cli`` package
------------------------------------------------

This module used to sit at the repo root as a top-level ``matlens_env_compat``
module (declared in ``pyproject.toml``'s ``py-modules`` list).  That
placement was a bootstrap hazard: a top-level module only resolves through
the editable-install finder, whose module map is baked at install time.  A
user who pulled the rename and ran the CLI before re-installing would get
``ModuleNotFoundError`` on a *startup* import — and because
``matlens_bootstrap`` (imported first by every entry point) transitively
imported this module, the whole CLI failed to boot, leaving the user unable
to run ``matlens update`` to repair the install.

Inside a package the situation is different: the editable finder resolves
``matlens_cli.env_compat`` through the already-mapped ``matlens_cli``
package directory, so the file is found the moment it lands on disk — no
re-install required.  Same for a wheel install, where the module ships as
part of the package rather than as a separate top-level file.
"""

from __future__ import annotations

import os

__all__ = [
    "LEGACY_ENV_ALIASES",
    "matlens_env",
    "matlens_env_flag",
]


#: Mapping of ``MATLENS_*`` name → legacy ``HERMES_*`` name.
#:
#: Only *functional* variables belong here — flags, tokens and file
#: locations that are always written by the same process that reads them.
#: Path-like variables that determine *where user data lives* must not be
#: aliased, because the old and new names historically pointed at different
#: directories (see the module docstring).
LEGACY_ENV_ALIASES: dict[str, str] = {
    "MATLENS_DASHBOARD_SESSION_TOKEN": "HERMES_DASHBOARD_SESSION_TOKEN",
    "MATLENS_DESKTOP": "HERMES_DESKTOP",
    "MATLENS_DESKTOP_READY_FILE": "HERMES_DESKTOP_READY_FILE",
    "MATLENS_DESKTOP_TERMINAL": "HERMES_DESKTOP_TERMINAL",
    "MATLENS_WEB_DIST": "HERMES_WEB_DIST",
    # Portal / OAuth wiring. The provisioning path (``dashboard_register``)
    # stamps these into ``.env`` under the new names while the auth plugin
    # used to read the old ones — so a provisioned client_id was written to
    # disk and then never picked up. Both halves now agree on the new name
    # with the legacy one as fallback.
    "MATLENS_DASHBOARD_OAUTH_CLIENT_ID": "HERMES_DASHBOARD_OAUTH_CLIENT_ID",
    "MATLENS_DASHBOARD_PORTAL_URL": "HERMES_DASHBOARD_PORTAL_URL",
    "MATLENS_PORTAL_BASE_URL": "HERMES_PORTAL_BASE_URL",
    # Dashboard runtime knobs.  The container's s6 run scripts still export
    # the HERMES_* spellings (they are documented as the operator-facing
    # contract), while the Python dashboard reads MATLENS_*.  Aliasing keeps
    # an existing docker-compose / .env file working across the rename.
    "MATLENS_DASHBOARD": "HERMES_DASHBOARD",
    "MATLENS_DASHBOARD_HOST": "HERMES_DASHBOARD_HOST",
    "MATLENS_DASHBOARD_PORT": "HERMES_DASHBOARD_PORT",
    "MATLENS_DASHBOARD_INSECURE": "HERMES_DASHBOARD_INSECURE",
    "MATLENS_DASHBOARD_BASIC_AUTH_USERNAME": "HERMES_DASHBOARD_BASIC_AUTH_USERNAME",
    "MATLENS_DASHBOARD_BASIC_AUTH_PASSWORD": "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD",
    "MATLENS_DASHBOARD_BASIC_AUTH_PASSWORD_HASH": "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH",
    "MATLENS_DASHBOARD_BASIC_AUTH_SECRET": "HERMES_DASHBOARD_BASIC_AUTH_SECRET",
    "MATLENS_DASHBOARD_BASIC_AUTH_TTL_SECONDS": "HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS",
    # Container runtime knobs.  The published docker-compose files and
    # operator-set .env files still use the HERMES_* spellings; the Python
    # side reads MATLENS_*.  Aliasing keeps an existing deployment working.
    "MATLENS_WRITE_SAFE_ROOT": "HERMES_WRITE_SAFE_ROOT",
    "MATLENS_DISABLE_LAZY_INSTALLS": "HERMES_DISABLE_LAZY_INSTALLS",
    "MATLENS_LAZY_INSTALL_TARGET": "HERMES_LAZY_INSTALL_TARGET",
}


def matlens_env(name: str, default: str | None = None) -> str | None:
    """Return ``name`` from the environment, falling back to its legacy alias.

    The canonical ``MATLENS_*`` name always wins.  The legacy ``HERMES_*``
    name is consulted only when the canonical one is unset or blank, so a
    caller can still override the legacy variable without it shadowing the
    new one.

    Names with no registered legacy alias behave like a plain
    ``os.environ.get``.
    """
    value = os.environ.get(name, "")
    if value.strip():
        return value

    legacy_name = LEGACY_ENV_ALIASES.get(name)
    if legacy_name:
        legacy_value = os.environ.get(legacy_name, "")
        if legacy_value.strip():
            return legacy_value

    if default is None:
        return None
    return default


def matlens_env_flag(name: str) -> bool:
    """Return whether the flag ``name`` is set to a truthy value.

    Accepts the same truthy spellings as the surrounding codebase
    (``1``, ``true``, ``yes``, ``on`` — case-insensitive).
    """
    value = matlens_env(name, "") or ""
    return value.strip().lower() in {"1", "true", "yes", "on"}
