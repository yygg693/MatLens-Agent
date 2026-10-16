"""Tests for the Nous-MatLens-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"matlens"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``matlens-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "matlens" tag namespace.

``is_nous_matlens_non_agentic`` should only match the actual Nous Research
MatLens-3 / MatLens-4 chat family.
"""

from __future__ import annotations

import pytest

from matlens_cli.model_switch import (
    _MATLENS_MODEL_WARNING,
    _check_matlens_model_warning,
    is_nous_matlens_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/MatLens-3-Llama-3.1-70B",
        "NousResearch/MatLens-3-Llama-3.1-405B",
        "matlens-3",
        "MatLens-3",
        "matlens-4",
        "matlens-4-405b",
        "matlens_4_70b",
        "openrouter/matlens3:70b",
        "openrouter/nousresearch/hermes-4-405b",
        "NousResearch/MatLens3",
        "matlens-3.1",
    ],
)
def test_matches_real_nous_matlens_chat_models(model_name: str) -> None:
    assert is_nous_matlens_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous MatLens 3/4"
    )
    assert _check_matlens_model_warning(model_name) == _MATLENS_MODEL_WARNING


