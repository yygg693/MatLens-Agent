"""Resolve MATLENS_HOME for standalone skill scripts.

Skill scripts may run outside the MatLens process (e.g. system Python,
nix env, CI) where ``matlens_constants`` is not importable.  This module
provides the same ``get_matlens_home()`` and ``display_matlens_home()``
contracts as ``matlens_constants`` without requiring it on ``sys.path``.

When ``matlens_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``matlens_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``MATLENS_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from matlens_constants import display_matlens_home as display_matlens_home
    from matlens_constants import get_matlens_home as get_matlens_home
except (ModuleNotFoundError, ImportError):

    def get_matlens_home() -> Path:
        """Return the MatLens home directory (default: ~/.matlens).

        Mirrors ``matlens_constants.get_matlens_home()``."""
        val = os.environ.get("MATLENS_HOME", "").strip()
        return Path(val) if val else Path.home() / ".matlens"

    def display_matlens_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``matlens_constants.display_matlens_home()``."""
        home = get_matlens_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
