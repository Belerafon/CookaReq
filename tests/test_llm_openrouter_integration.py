import os
from pathlib import Path

import pytest

from tests.llm_utils import settings_with_llm
from app.llm.client import LLMClient


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


@pytest.mark.real_llm
def test_openrouter_check_llm(tmp_path):
    if not os.getenv("COOKAREQ_RUN_REAL_LLM_TESTS"):
        pytest.skip("Set COOKAREQ_RUN_REAL_LLM_TESTS=1 to enable this test")
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key)
    client = LLMClient(settings.llm)
    result = client.check_llm()
    assert result["ok"] is True
