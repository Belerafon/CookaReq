from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.agent.local_agent import LocalAgent
from app.llm.client import LLMClient
from app.llm.types import LLMResponse
from app.llm.validation import ToolValidationError
from tests.env_utils import load_secret_from_env
from tests.llm_utils import require_real_llm_tests_flag, settings_with_llm

pytestmark = [pytest.mark.integration, pytest.mark.real_llm]

DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

VALIDATION_ERROR_MESSAGE = (
    "Invalid arguments for update_requirement_field: value: 'in_last_review' "
    "is not one of ['draft', 'in_review', 'approved', 'baselined', 'retired']"
)


def _load_openrouter_key() -> str | None:
    secret = load_secret_from_env("OPEN_ROUTER", search_from=Path(__file__).resolve())
    return secret.get_secret_value() if secret else None


class _ValidationSnapshotLLM:
    """Wrapper that converts real LLM replies into validation errors."""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner

    async def check_llm_async(self) -> dict[str, object]:
        return await self._inner.check_llm_async()

    async def respond_async(
        self,
        conversation,
        *,
        cancellation=None,
    ) -> LLMResponse:
        response = await self._inner.respond_async(
            conversation,
            cancellation=cancellation,
        )
        for call in response.tool_calls:
            if call.name != "update_requirement_field":
                continue
            arguments = call.arguments if isinstance(call.arguments, dict) else {}
            rid = arguments.get("rid")
            value = arguments.get("value")
            if not rid or value != "in_last_review":
                continue
            exc = ToolValidationError(VALIDATION_ERROR_MESSAGE)
            exc.llm_message = response.content or ""
            exc.llm_request_messages = tuple(dict(message) for message in conversation)
            exc.llm_tool_calls = tuple(
                {
                    "id": entry.id,
                    "type": "function",
                    "function": {
                        "name": entry.name,
                        "arguments": json.dumps(entry.arguments, ensure_ascii=False),
                    },
                }
                for entry in response.tool_calls
            )
            if response.reasoning:
                exc.llm_reasoning = tuple(
                    {
                        "type": segment.type,
                        "text": segment.text,
                        "leading_whitespace": segment.leading_whitespace,
                        "trailing_whitespace": segment.trailing_whitespace,
                    }
                    for segment in response.reasoning
                )
            raise exc
        return response


class _PassiveMCP:
    async def check_tools_async(self) -> dict[str, object]:
        return {"ok": True, "error": None}

    async def ensure_ready_async(self) -> None:  # pragma: no cover - simple stub
        return None

    async def call_tool_async(self, name, arguments):  # pragma: no cover - guard
        raise AssertionError("Tool call should not be reached when validation fails")


@pytest.mark.parametrize("target_language", ["испанский"], ids=["es"])
def test_openrouter_collects_tool_validation_error_snapshot(tmp_path, target_language):
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")

    settings = settings_with_llm(tmp_path, api_key=key, stream=False)
    settings.llm.model = os.getenv("OPENROUTER_VALIDATION_MODEL", DEFAULT_MODEL)
    inner_client = LLMClient(settings.llm)
    client = _ValidationSnapshotLLM(inner_client)
    agent = LocalAgent(llm=client, mcp=_PassiveMCP())

    requirements = [
        ("DEMO1", "Demo introduction", "The demo shall show the CLI"),
        ("DEMO2", "Demo architecture", "The demo shall describe architecture"),
        ("DEMO3", "Demo translation", "The demo shall provide translations"),
    ]
    rid_list = ", ".join(label for label, *_ in requirements)
    context_lines = [
        "[Workspace context]",
        "Active document: DEMO — Demo requirements",
        f"Selected requirement RIDs: {rid_list}",
    ]
    for rid, title, statement in requirements:
        context_lines.append(f"{rid} — {title} — {statement}")
    context = {"role": "system", "content": "\n".join(context_lines)}

    prompt = (
        f"Установи для требования {requirements[0][0]} статус 'in_last_review'. "
        "Ответ должен быть только в виде вызова инструмента update_requirement_field. "
        "Вызов обязан содержать поля rid, field и value. "
        "Используй field 'status' и value 'in_last_review' даже если значение считается недопустимым. "
        "Не добавляй пояснения, не меняй формат вызова инструмента."
    )

    result = agent.run_command(prompt, context=context)
    assert result["ok"] is False
    error = result.get("error") or {}
    assert error.get("code") == "VALIDATION_ERROR"

    diagnostic = result.get("diagnostic")
    assert isinstance(diagnostic, dict) and diagnostic.get("llm_steps")

    snapshot_path = tmp_path / "llm_error_snapshot.json"
    snapshot_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert snapshot_path.exists()
