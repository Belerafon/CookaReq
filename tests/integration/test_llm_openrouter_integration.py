from __future__ import annotations

from pathlib import Path

import os

import pytest

from app.llm.client import LLMClient
from tests.env_utils import load_secret_from_env
from tests.llm_utils import require_real_llm_tests_flag, settings_with_llm

REQUIRES_REAL_LLM = True

pytestmark = [pytest.mark.integration, pytest.mark.real_llm]


def _load_openrouter_key() -> str | None:
    secret = load_secret_from_env("OPEN_ROUTER", search_from=Path(__file__).resolve())
    return secret.get_secret_value() if secret else None


def test_openrouter_check_llm(tmp_path):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key)
    client = LLMClient(settings.llm)
    result = client.check_llm()
    assert result["ok"] is True


def test_openrouter_handles_context_prompt(tmp_path):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key)
    client = LLMClient(settings.llm)
    conversation = [
        {
            "role": "system",
            "content": (
                "[Workspace context]\n"
                "Active requirements list: SYS — System Requirements\n"
                "Selected requirement RIDs: SYS-1"
            ),
        },
        {
            "role": "user",
            "content": "fix the description in the selected requirement",
        },
    ]
    response = client.respond(conversation)
    assert isinstance(response.content, str)
DEFAULT_FREE_REASONING_MODEL = "x-ai/grok-4-fast:free"


def _select_reasoning_model() -> str:
    """Return the OpenRouter model used for reasoning checks."""

    model = os.getenv("OPENROUTER_REASONING_MODEL")
    if model and model.strip():
        return model.strip()
    return DEFAULT_FREE_REASONING_MODEL


def test_openrouter_reasoning_segments(tmp_path):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key)
    settings.llm.model = _select_reasoning_model()
    client = LLMClient(settings.llm)
    conversation = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "Summarize 2+2."},
    ]
    response = client.respond(conversation)
    assert response.reasoning
