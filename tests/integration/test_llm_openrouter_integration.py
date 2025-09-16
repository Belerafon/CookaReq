import os
from pathlib import Path

import pytest

from app.llm.client import LLMClient
from tests.llm_utils import require_real_llm_tests_flag, settings_with_llm

REQUIRES_REAL_LLM = True

pytestmark = [pytest.mark.integration, pytest.mark.real_llm]


def _load_openrouter_key() -> str | None:
    key = os.getenv("OPEN_ROUTER")
    if key:
        return key
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("OPEN_ROUTER="):
                return line.split("=", 1)[1].strip()
    return None


def test_openrouter_check_llm(tmp_path):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key)
    client = LLMClient(settings.llm)
    result = client.check_llm()
    assert result["ok"] is True
