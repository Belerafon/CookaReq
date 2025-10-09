from __future__ import annotations

import os

from tests.suite_utils import auto_opt_in_real_llm_suite


def test_auto_opt_in_respects_existing_flag(monkeypatch):
    monkeypatch.setenv("COOKAREQ_RUN_REAL_LLM_TESTS", "already-set")
    monkeypatch.setenv("OPEN_ROUTER", "from-env")

    result = auto_opt_in_real_llm_suite()

    assert result is True
    assert os.environ["COOKAREQ_RUN_REAL_LLM_TESTS"] == "already-set"


def test_auto_opt_in_sets_flag_when_secret_found(monkeypatch, tmp_path):
    monkeypatch.delenv("COOKAREQ_RUN_REAL_LLM_TESTS", raising=False)
    monkeypatch.delenv("OPEN_ROUTER", raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text("OPEN_ROUTER=from-dotenv\n", encoding="utf-8")
    nested = tmp_path / "child"
    nested.mkdir()

    result = auto_opt_in_real_llm_suite(search_from=nested)

    assert result is True
    assert os.environ["COOKAREQ_RUN_REAL_LLM_TESTS"] == "1"


def test_auto_opt_in_returns_false_when_secret_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("COOKAREQ_RUN_REAL_LLM_TESTS", raising=False)
    monkeypatch.delenv("OPEN_ROUTER", raising=False)

    result = auto_opt_in_real_llm_suite(search_from=tmp_path)

    assert result is False
    assert "COOKAREQ_RUN_REAL_LLM_TESTS" not in os.environ
