from pathlib import Path

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
                "Selected requirements (1):\n"
                "- SYS-1 (id=1, prefix=SYS) — Demo"
            ),
        },
        {
            "role": "user",
            "content": "удали это требование",
        },
    ]
    response = client.respond(conversation)
    assert isinstance(response.content, str)
