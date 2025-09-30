from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.llm.client import LLMClient
from app.mcp.tools_read import get_requirement
from tests.env_utils import load_secret_from_env
from tests.llm_utils import require_real_llm_tests_flag, settings_with_llm

REQUIRES_REAL_LLM = True

pytestmark = [pytest.mark.integration, pytest.mark.real_llm]


def _load_openrouter_key() -> str | None:
    secret = load_secret_from_env("OPEN_ROUTER", search_from=Path(__file__).resolve())
    return secret.get_secret_value() if secret else None


@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
def test_openrouter_check_llm(tmp_path, stream):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key, stream=stream)
    client = LLMClient(settings.llm)
    result = client.check_llm()
    assert result["ok"] is True


@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
def test_openrouter_handles_context_prompt(tmp_path, stream):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key, stream=stream)
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


@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
def test_openrouter_reasoning_segments(tmp_path, stream):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key, stream=stream)
    settings.llm.model = _select_reasoning_model()
    client = LLMClient(settings.llm)
    conversation = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "Summarize 2+2."},
    ]
    response = client.respond(conversation)
    assert response.reasoning


def test_openrouter_updates_selected_requirement_translations(tmp_path):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")
    settings = settings_with_llm(tmp_path, api_key=key, stream=False)
    settings.llm.model = "gpt-oss-120b"
    client = LLMClient(settings.llm)

    context = (
        "[Workspace context]\n"
        "Active document: DEMO — Demo requirements\n"
        "Selected requirement RIDs: DEMO6, DEMO7, DEMO8, DEMO9\n"
        "DEMO6 — CLI in the demo — The demo must contain a CLI section showing how commands reuse the core, "
        "which subcommands are available, and what configuration is required for headless execution.\n"
        "DEMO7 — Auxiliary modules overview — Demo materials must list auxiliary modules (settings, localisation, logging), "
        "describe usage rules, and point out potential refactoring targets.\n"
        "DEMO8 — End-to-end scenarios — The demo package must include at least three end-to-end scenarios "
        "(open project, edit requirement, generate report) with the sequence of cross-layer interactions.\n"
        "DEMO9 — Risk and task table — The demo description must include a risk and task table for the architecture, "
        "including automation ideas and control checks.\n"
    )
    user_prompt = (
        "Переведи выделенные требования на русский, используй update_requirement_field для каждого из них. Внеси такие значения:\n"
        "DEMO6 — заголовок \"Демонстрация должна содержать раздел CLI\"; формулировка \"Демонстрация должна содержать раздел CLI, "
        "показывающий, как команды используют ядро, какие подкоманды доступны и какая конфигурация требуется для безголового выполнения.\"\n"
        "DEMO7 — заголовок \"Вспомогательные модули\"; формулировка \"Материалы демонстрации должны перечислять вспомогательные модули "
        "(настройки, локализация, логирование), описывать правила использования и указывать потенциальные цели для рефакторинга.\"\n"
        "DEMO8 — заголовок \"Сквозные сценарии\"; формулировка \"Пакет демонстрации должен включать как минимум три сквозных сценария "
        "(открыть проект, отредактировать требование, сформировать отчет) с последовательностью межслойных взаимодействий.\"\n"
        "DEMO9 — заголовок \"Таблица рисков и задач\"; формулировка \"Описание демонстрации должно содержать таблицу рисков и задач для "
        "архитектуры, включая идеи автоматизации и контрольные проверки.\"\n"
    )

    conversation: list[dict[str, object]] = [
        {"role": "system", "content": context},
        {"role": "user", "content": user_prompt},
    ]

    update_call = None
    for _ in range(5):
        response = client.respond(conversation)
        assistant_entry: dict[str, object] = {
            "role": "assistant",
            "content": response.content or " ",
        }
        call = response.tool_calls[0] if response.tool_calls else None
        if call is not None:
            assistant_entry["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
            ]
        conversation.append(assistant_entry)
        if call is None:
            continue
        if call.name == "get_requirement":
            payload = get_requirement(
                Path("requirements"),
                rid=["DEMO6", "DEMO7", "DEMO8", "DEMO9"],
                fields=["title", "statement"],
            )
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": json.dumps(payload, ensure_ascii=False),
                }
            )
            continue
        update_call = call
        break

    assert update_call is not None, "model did not request an update"
    assert update_call.name == "update_requirement_field"
    arguments = update_call.arguments
    assert arguments.get("rid") == "DEMO6"
    assert arguments.get("field") in {"title", "statement"}
    assert isinstance(arguments.get("value"), str) and arguments["value"].strip()
