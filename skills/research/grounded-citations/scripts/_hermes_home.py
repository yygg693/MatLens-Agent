"""Resolve MATLENS_HOME for standalone skill scripts.

Skill scripts may run outside the MatLens process (system Python, nix env,
CI) where ``matlens_constants`` is not importable.  This module provides the
same ``get_matlens_home()`` contract without requiring it on ``sys.path``.

When ``matlens_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from matlens_constants import get_matlens_home as get_matlens_home
except (ModuleNotFoundError, ImportError):

    def get_matlens_home() -> Path:
        """Return the MatLens home directory (default: ``~/.matlens``)."""
        val = os.environ.get("MATLENS_HOME", "").strip()
        return Path(val) if val else Path.home() / ".matlens"
