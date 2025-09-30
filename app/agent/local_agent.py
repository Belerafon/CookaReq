"""Local agent that combines LLM parsing with MCP tool execution."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from ..confirm import (
    ConfirmDecision,
    RequirementUpdatePrompt,
    confirm as default_confirm,
    confirm_requirement_update as default_update_confirm,
)
from ..services.requirements import parse_rid
from ..llm.context import extract_selected_rids_from_text
from ..llm.client import LLMClient
from ..llm.reasoning import normalise_reasoning_segments
from ..llm.types import LLMReasoningSegment, LLMResponse, LLMToolCall
from ..llm.validation import ToolValidationError
from ..mcp.client import MCPClient
from ..mcp.utils import exception_to_mcp_error
from ..settings import AppSettings
from ..telemetry import log_debug_payload, log_event
from ..util.cancellation import (
    CancellationEvent,
    OperationCancelledError,
    raise_if_cancelled,
)


@runtime_checkable
class SupportsAgentLLM(Protocol):
    """Interface expected from LLM clients used by :class:`LocalAgent`."""

    async def check_llm_async(self) -> Mapping[str, Any]:
        """Verify that the LLM backend is reachable."""

    async def respond_async(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Return an assistant reply for *conversation*."""


@runtime_checkable
class SupportsAgentMCP(Protocol):
    """Interface expected from MCP clients used by :class:`LocalAgent`."""

    async def check_tools_async(self) -> Mapping[str, Any]:
        """Verify that MCP tools are reachable."""

    async def ensure_ready_async(self) -> None:
        """Raise an exception when the MCP server is not ready."""

    async def call_tool_async(
        self, name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Invoke MCP tool *name* with *arguments*."""


class LocalAgent:
    """High-level agent aggregating LLM and MCP clients."""

    DEFAULT_MAX_THOUGHT_STEPS: int | None = None
    DEFAULT_MAX_CONSECUTIVE_TOOL_ERRORS: int | None = 5
    _MESSAGE_PREVIEW_LIMIT = 400
    _REQUIREMENT_SUMMARY_FIELDS: tuple[str, str] = ("title", "statement")

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        llm: SupportsAgentLLM | None = None,
        mcp: SupportsAgentMCP | None = None,
        confirm: Callable[[str], bool] | None = None,
        confirm_requirement_update: Callable[[RequirementUpdatePrompt], ConfirmDecision]
        | None = None,
        max_thought_steps: int | None = None,
        max_consecutive_tool_errors: int | None = None,
    ) -> None:
        """Initialize agent with optional settings or prebuilt clients."""
        if settings is not None:
            if confirm is None:
                confirm = default_confirm
            if confirm_requirement_update is None:
                confirm_requirement_update = default_update_confirm
            if llm is None:
                llm = LLMClient(settings.llm)
            if mcp is None:
                mcp = MCPClient(
                    settings.mcp,
                    confirm=confirm,
                    confirm_requirement_update=confirm_requirement_update,
                )
            if max_thought_steps is None:
                max_thought_steps = settings.agent.max_thought_steps
            if max_consecutive_tool_errors is None:
                max_consecutive_tool_errors = (
                    settings.agent.max_consecutive_tool_errors
                )
        if llm is None or mcp is None:
            raise TypeError("settings or clients must be provided")
        if not isinstance(llm, SupportsAgentLLM):
            raise TypeError(
                "LLM client must implement async methods check_llm_async() and "
                "respond_async()."
            )
        if not isinstance(mcp, SupportsAgentMCP):
            raise TypeError(
                "MCP client must implement async methods check_tools_async(), "
                "ensure_ready_async(), and call_tool_async()."
            )
        self._llm: SupportsAgentLLM = llm
        self._mcp: SupportsAgentMCP = mcp
        self._llm_requests: list[list[dict[str, Any]]] = []
        self._llm_steps: list[dict[str, Any]] = []
        self._max_thought_steps: int | None = self._normalise_max_thought_steps(
            max_thought_steps
        )
        self._max_consecutive_tool_errors: int | None = (
            self._normalise_max_consecutive_tool_errors(max_consecutive_tool_errors)
        )

    # ------------------------------------------------------------------
    @classmethod
    def _preview(cls, text: str, limit: int | None = None) -> str:
        """Return a trimmed preview of *text* for logging."""

        limit = limit or cls._MESSAGE_PREVIEW_LIMIT
        snippet = text.strip()
        if len(snippet) > limit:
            return snippet[: limit - 1] + "\u2026"
        return snippet

    @staticmethod
    def _summarize_tool_calls(tool_calls: Sequence[LLMToolCall]) -> list[dict[str, Any]]:
        """Return lightweight metadata about planned tool calls."""

        summary: list[dict[str, Any]] = []
        for call in tool_calls:
            args = call.arguments if isinstance(call.arguments, Mapping) else {}
            summary.append(
                {
                    "id": call.id,
                    "name": call.name,
                    "argument_keys": sorted(args.keys()) if isinstance(args, Mapping) else [],
                }
            )
        return summary

    @staticmethod
    def _tool_call_debug_payload(call: LLMToolCall) -> dict[str, Any]:
        """Return detailed payload describing *call* for debug logging."""

        arguments: Any
        if isinstance(call.arguments, Mapping):
            arguments = dict(call.arguments)
        else:
            arguments = call.arguments
        return {
            "id": call.id,
            "name": call.name,
            "arguments": arguments,
        }

    @staticmethod
    def _normalise_request_messages(
        messages: Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Return a shallow copy of *messages* suitable for logging."""

        if not messages:
            return []
        prepared: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, Mapping):
                prepared.append(dict(message))
        return prepared

    def _log_step(self, step: int, response: LLMResponse) -> dict[str, Any]:
        """Record intermediate agent step for diagnostics."""

        normalized_reasoning = normalise_reasoning_segments(response.reasoning)
        payload = {
            "step": step,
            "message_preview": self._preview(response.content),
            "tool_calls": self._summarize_tool_calls(response.tool_calls),
        }
        if normalized_reasoning:
            payload["reasoning"] = [
                {
                    "type": segment["type"],
                    "preview": self._preview(segment["text"], limit=200),
                }
                for segment in normalized_reasoning
            ]
        detail_payload = {
            "step": step,
            "response": {
                "content": response.content,
                "tool_calls": [
                    self._tool_call_debug_payload(call)
                    for call in response.tool_calls
                ],
                "reasoning": normalized_reasoning,
            },
            "request_messages": self._normalise_request_messages(
                response.request_messages
            ),
        }
        log_event("AGENT_STEP", payload)
        log_debug_payload("AGENT_STEP_DETAIL", detail_payload)
        self._llm_steps.append(detail_payload)
        return detail_payload

    @classmethod
    def _summarize_result(cls, result: Mapping[str, Any]) -> dict[str, Any]:
        """Return compact metadata about final agent outcome."""

        payload: dict[str, Any] = {}
        ok_value = result.get("ok")
        if isinstance(ok_value, bool):
            payload["ok"] = ok_value
        if "error" in result and result["error"]:
            payload["error"] = result["error"]
        if "result" in result and result["result"]:
            payload["result_type"] = type(result["result"]).__name__
            if isinstance(result["result"], str) and result["result"].strip():
                payload["result_preview"] = cls._preview(result["result"])
        if "tool_results" in result:
            try:
                payload["tool_results"] = len(result["tool_results"])
            except TypeError:
                payload["tool_results"] = result["tool_results"]
        stop_reason = result.get("agent_stop_reason")
        if isinstance(stop_reason, Mapping):
            payload["agent_stop_reason"] = dict(stop_reason)
        reasoning_segments = result.get("reasoning")
        normalized_reasoning = normalise_reasoning_segments(reasoning_segments)
        if normalized_reasoning:
            payload["reasoning"] = [
                {
                    "type": segment["type"],
                    "preview": cls._preview(segment["text"], limit=200),
                }
                for segment in normalized_reasoning
            ]
        return payload

    @staticmethod
    def _format_validation_fallback_message(
        error_template: Mapping[str, Any]
    ) -> str:
        """Compose a human-readable fallback message from *error_template*."""

        message = str(error_template.get("message") or "").strip()
        details = error_template.get("details")
        detail_parts: list[str] = []
        if isinstance(details, Mapping):
            for key, value in details.items():
                if key in {
                    "llm_tool_calls",
                    "llm_request_messages",
                    "tool_results",
                }:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                detail_parts.append(f"{key}: {text}")
        elif details is not None:
            text = str(details).strip()
            if text:
                detail_parts.append(text)
        if detail_parts:
            details_text = "; ".join(detail_parts)
            if message:
                return f"{message} ({details_text})"
            return details_text
        return message or "Tool call failed validation."

    def _record_request_messages(self, response: LLMResponse) -> None:
        """Append request snapshot from *response* to diagnostic log."""

        snapshot = getattr(response, "request_messages", None)
        if not snapshot:
            return
        messages: list[dict[str, Any]] = []
        for message in snapshot:
            if isinstance(message, Mapping):
                messages.append(dict(message))
        if messages:
            self._llm_requests.append(messages)

    def _prepare_result_with_diagnostic(
        self, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Attach captured LLM request messages to ``result`` when available."""

        prepared = dict(result)
        diagnostic_payload: dict[str, Any] = {}
        existing = prepared.get("diagnostic")
        if isinstance(existing, Mapping):
            diagnostic_payload.update(existing)
        if self._llm_requests:
            requests_payload = [
                {
                    "step": index + 1,
                    "messages": [dict(message) for message in messages],
                }
                for index, messages in enumerate(self._llm_requests)
            ]
            diagnostic_payload["llm_requests"] = requests_payload
        if self._llm_steps:
            step_payloads: list[dict[str, Any]] = []
            for entry in self._llm_steps:
                if isinstance(entry, Mapping):
                    step_payloads.append(dict(entry))
            if step_payloads:
                diagnostic_payload["llm_steps"] = step_payloads
        if diagnostic_payload:
            prepared["diagnostic"] = diagnostic_payload
        return prepared

    @staticmethod
    def _extract_mcp_error(exc: Exception) -> dict[str, Any]:
        """Return structured MCP error payload derived from *exc*."""

        payload = getattr(exc, "error_payload", None)
        if isinstance(payload, Mapping):
            return dict(payload)
        payload = getattr(exc, "error", None)
        if isinstance(payload, Mapping):
            return dict(payload)
        return exception_to_mcp_error(exc)["error"]

    @staticmethod
    def _raise_if_cancelled(cancellation: CancellationEvent | None) -> None:
        """Abort execution when *cancellation* has been triggered."""

        raise_if_cancelled(cancellation)

    @staticmethod
    def _normalise_max_thought_steps(value: int | None) -> int | None:
        """Return sanitized upper bound for agent iterations."""

        if value is None:
            return LocalAgent.DEFAULT_MAX_THOUGHT_STEPS
        if isinstance(value, bool):  # pragma: no cover - defensive guard
            raise TypeError("max_thought_steps must be an integer or None")
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError("max_thought_steps must be an integer or None") from exc
        if numeric <= 0:
            return LocalAgent.DEFAULT_MAX_THOUGHT_STEPS
        return numeric

    @property
    def max_thought_steps(self) -> int | None:
        """Return currently configured step cap (``None`` means unlimited)."""

        return self._max_thought_steps

    @staticmethod
    def _normalise_max_consecutive_tool_errors(value: int | None) -> int | None:
        """Return sanitised cap for consecutive tool failures."""

        if value is None:
            return LocalAgent.DEFAULT_MAX_CONSECUTIVE_TOOL_ERRORS
        if isinstance(value, bool):  # pragma: no cover - defensive guard
            raise TypeError(
                "max_consecutive_tool_errors must be an integer or None"
            )
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError(
                "max_consecutive_tool_errors must be an integer or None"
            ) from exc
        if numeric <= 0:
            return None
        return numeric

    @property
    def max_consecutive_tool_errors(self) -> int | None:
        """Return cap for consecutive tool failures (``None`` disables limit)."""

        return self._max_consecutive_tool_errors

    @staticmethod
    def _run_sync(coro: Awaitable[Any]) -> Any:
        """Execute asynchronous helpers from synchronous entry points."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "Synchronous LocalAgent methods cannot run inside an active "
            "asyncio event loop; use the async variants instead."
        )

    @staticmethod
    def _normalise_context(
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not context:
            return []
        if isinstance(context, Mapping):
            role = context.get("role")
            if role is None:
                return []
            return [
                {
                    "role": str(role),
                    "content": ""
                    if context.get("content") is None
                    else str(context.get("content")),
                }
            ]
        normalised: list[dict[str, Any]] = []
        for message in context:
            if not isinstance(message, Mapping):
                continue
            role = message.get("role")
            if role is None:
                continue
            entry: dict[str, Any] = {
                "role": str(role),
                "content": ""
                if message.get("content") is None
                else str(message.get("content")),
            }
            if "tool_calls" in message and isinstance(
                message.get("tool_calls"), Sequence
            ):
                entry["tool_calls"] = message.get("tool_calls")
            normalised.append(entry)
        return normalised

    def _prepare_conversation(
        self,
        text: str,
        history: Sequence[Mapping[str, Any]] | None,
        *,
        context: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[Mapping[str, Any]]:
        conversation: list[Mapping[str, Any]] = list(history or [])
        if context:
            conversation.extend(context)
        conversation.append({"role": "user", "content": text})
        return conversation

    def _prepare_context_messages(
        self, context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
    ) -> list[Mapping[str, Any]]:
        return self._run_sync(self._prepare_context_messages_async(context))

    async def _prepare_context_messages_async(
        self, context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
    ) -> list[Mapping[str, Any]]:
        messages = self._normalise_context(context)
        if not messages:
            return []
        await self._enrich_workspace_context_async(messages)
        return messages

    async def _enrich_workspace_context_async(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> None:
        """Append summaries for selected requirements to workspace context messages."""
        for message in messages:
            role = message.get("role") if isinstance(message, Mapping) else None
            if role != "system":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            stripped = content.lstrip()
            if not stripped.startswith("[Workspace context]"):
                continue
            selected_rids = self._extract_selected_rids_from_context(content)
            if not selected_rids:
                continue
            existing_lines = content.splitlines()
            already_present = {
                line.split(" — ", 1)[0].strip()
                for line in existing_lines
                if " — " in line
            }
            to_fetch: list[str] = []
            seen: set[str] = set()
            for rid in selected_rids:
                if rid in already_present or rid in seen:
                    continue
                to_fetch.append(rid)
                seen.add(rid)
            if not to_fetch:
                continue
            summaries = await self._fetch_requirement_summaries_async(to_fetch)
            if not summaries:
                continue
            additions: list[str] = []
            for rid in to_fetch:
                summary = summaries.get(rid)
                if not summary:
                    continue
                additions.append(f"{rid} — {summary}")
            if additions:
                message["content"] = "\n".join([*existing_lines, *additions])

    @staticmethod
    def _extract_selected_rids_from_context(content: str) -> list[str]:
        return extract_selected_rids_from_text(content)

    async def _fetch_requirement_summaries_async(
        self, rids: Sequence[str]
    ) -> dict[str, str]:
        """Return requirement statements or titles for the given ``rids``."""
        unique: list[str] = []
        seen: set[str] = set()
        for rid in rids:
            if rid in seen:
                continue
            unique.append(rid)
            seen.add(rid)
        if not unique:
            return {}
        try:
            response = await self._mcp.call_tool_async(
                "get_requirement",
                {"rid": unique, "fields": list(self._REQUIREMENT_SUMMARY_FIELDS)},
            )
        except Exception:
            return {}
        if not isinstance(response, Mapping):
            return {}
        if response.get("ok") is not True:
            return {}
        result = response.get("result")
        if not isinstance(result, Mapping):
            return {}
        items = result.get("items")
        if not isinstance(items, Sequence):
            return {}
        summaries: dict[str, str] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            rid_value = str(item.get("rid") or "").strip()
            if not rid_value:
                continue
            statement = str(item.get("statement") or "").strip()
            summary = statement or str(item.get("title") or "").strip()
            if not summary:
                continue
            summaries[rid_value] = summary
        return summaries

    # ------------------------------------------------------------------
    def check_llm(self) -> dict[str, Any]:
        """Delegate to :class:`LLMClient.check_llm`."""

        return self._run_sync(self._llm.check_llm_async())

    async def check_llm_async(self) -> dict[str, Any]:
        """Asynchronous variant of :meth:`check_llm`."""

        return await self._llm.check_llm_async()

    # ------------------------------------------------------------------
    def check_tools(self) -> dict[str, Any]:
        """Delegate to :class:`MCPClient.check_tools`."""

        return self._run_sync(self._mcp.check_tools_async())

    async def check_tools_async(self) -> dict[str, Any]:
        """Asynchronous variant of :meth:`check_tools`."""

        return await self._mcp.check_tools_async()

    # ------------------------------------------------------------------
    def run_command(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
        on_llm_step: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Drive an agent loop that may invoke MCP tools before replying."""

        context_messages = self._prepare_context_messages(context)
        conversation = self._prepare_conversation(
            text,
            history,
            context=context_messages,
        )
        log_event(
            "AGENT_START",
            {"history_count": len(history or []), "prompt": self._preview(text, 200)},
        )
        self._llm_requests = []
        self._llm_steps = []
        try:
            result = self._run_sync(
                self._run_loop_core(
                    conversation,
                    cancellation=cancellation,
                    on_tool_result=on_tool_result,
                    on_llm_step=on_llm_step,
                )
            )
        except OperationCancelledError:
            log_event("AGENT_CANCELLED", {"reason": "user-request"})
            raise
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return self._prepare_result_with_diagnostic({"ok": False, "error": err})
        log_event("AGENT_RESULT", self._summarize_result(result))
        return self._prepare_result_with_diagnostic(result)

    async def run_command_async(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
        on_llm_step: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Asynchronous variant of :meth:`run_command`."""

        context_messages = await self._prepare_context_messages_async(context)
        conversation = self._prepare_conversation(
            text,
            history,
            context=context_messages,
        )
        log_event(
            "AGENT_START",
            {"history_count": len(history or []), "prompt": self._preview(text, 200)},
        )
        self._llm_requests = []
        self._llm_steps = []
        try:
            result = await self._run_loop_core(
                conversation,
                cancellation=cancellation,
                on_tool_result=on_tool_result,
                on_llm_step=on_llm_step,
            )
        except OperationCancelledError:
            log_event("AGENT_CANCELLED", {"reason": "user-request"})
            raise
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return self._prepare_result_with_diagnostic({"ok": False, "error": err})
        log_event("AGENT_RESULT", self._summarize_result(result))
        return self._prepare_result_with_diagnostic(result)

    # ------------------------------------------------------------------
    async def _run_loop_core(
        self,
        conversation: list[Mapping[str, Any]],
        *,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
        on_llm_step: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        runner = AgentLoopRunner(
            agent=self,
            conversation=conversation,
            cancellation=cancellation,
            on_tool_result=on_tool_result,
            on_llm_step=on_llm_step,
        )
        return await runner.run()

    async def _execute_tool_calls_core(
        self,
        tool_calls: Sequence[LLMToolCall],
        *,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[Mapping[str, Any]]]:
        messages: list[dict[str, Any]] = []
        successful: list[Mapping[str, Any]] = []
        for call in tool_calls:
            self._raise_if_cancelled(cancellation)
            try:
                self._emit_tool_result(
                    on_tool_result,
                    self._prepare_tool_payload(
                        call,
                        {"agent_status": "running"},
                        include_arguments=True,
                    ),
                )
                log_event(
                    "AGENT_TOOL_CALL",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "arguments": call.arguments,
                    },
                )
                log_debug_payload(
                    "AGENT_TOOL_CALL_DETAIL",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "arguments": self._normalise_tool_arguments(call),
                    },
                )
                await self._mcp.ensure_ready_async()
                result = await self._mcp.call_tool_async(call.name, call.arguments)
            except Exception as exc:
                error = self._extract_mcp_error(exc)
                log_event("ERROR", {"error": error})
                log_event(
                    "AGENT_TOOL_RESULT",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "ok": False,
                        "error": error,
                    },
                )
                payload = self._prepare_tool_payload(
                    call,
                    {"ok": False, "error": error},
                    include_arguments=True,
                )
                payload.setdefault("agent_status", "failed")
                self._emit_tool_result(on_tool_result, payload)
                log_debug_payload(
                    "AGENT_TOOL_RESULT_DETAIL",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "ok": False,
                        "error": error,
                        "arguments": self._normalise_tool_arguments(call),
                    },
                )
                messages.append(self._tool_message(call, payload))
                return messages, payload, successful
            if not isinstance(result, Mapping):
                payload = self._prepare_tool_payload(
                    call,
                    {
                        "ok": False,
                        "error": {
                            "type": "ToolProtocolError",
                            "message": "Tool returned unexpected payload",
                        },
                    },
                    include_arguments=True,
                )
                payload.setdefault("agent_status", "failed")
                self._emit_tool_result(on_tool_result, payload)
                log_debug_payload(
                    "AGENT_TOOL_RESULT_DETAIL",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "ok": False,
                        "raw_result": result,
                        "arguments": self._normalise_tool_arguments(call),
                    },
                )
                messages.append(self._tool_message(call, payload))
                return messages, payload, successful
            result_dict = self._prepare_tool_payload(
                call,
                result,
                include_arguments=True,
            )
            if result_dict.get("ok") is False:
                result_dict.setdefault("agent_status", "failed")
            else:
                result_dict.setdefault("agent_status", "completed")
            log_payload: dict[str, Any] = {
                "call_id": call.id,
                "tool_name": call.name,
                "ok": bool(result_dict.get("ok", False)),
            }
            if not log_payload["ok"] and result_dict.get("error"):
                log_payload["error"] = result_dict["error"]
            log_event("AGENT_TOOL_RESULT", log_payload)
            log_debug_payload(
                "AGENT_TOOL_RESULT_DETAIL",
                {
                    "call_id": call.id,
                    "tool_name": call.name,
                    "ok": bool(result.get("ok", False))
                    if isinstance(result, Mapping)
                    else False,
                    "result": result,
                    "arguments": self._normalise_tool_arguments(call),
                },
            )
            self._emit_tool_result(on_tool_result, result_dict)
            messages.append(self._tool_message(call, result_dict))
            if not result_dict.get("ok", False):
                return messages, result_dict, successful
            successful.append(result_dict)
            self._raise_if_cancelled(cancellation)
        return messages, None, successful

    def _handle_tool_validation_error(
        self,
        exc: ToolValidationError,
        conversation: list[Mapping[str, Any]],
        *,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> tuple[LLMResponse, Mapping[str, Any] | None]:
        message_text = getattr(exc, "llm_message", "") or ""
        raw_calls = getattr(exc, "llm_tool_calls", None)
        raw_request_messages = getattr(exc, "llm_request_messages", None)
        raw_reasoning = getattr(exc, "llm_reasoning", None)
        prepared_calls = self._prepare_invalid_tool_calls(raw_calls)
        request_snapshot: tuple[dict[str, Any], ...] | None = None
        normalized_reasoning = normalise_reasoning_segments(raw_reasoning)
        reasoning_segments: tuple[LLMReasoningSegment, ...] = ()
        if isinstance(raw_request_messages, Sequence) and not isinstance(
            raw_request_messages, (str, bytes, bytearray)
        ):
            prepared_messages: list[dict[str, Any]] = []
            for message in raw_request_messages:
                if isinstance(message, Mapping):
                    prepared_messages.append(dict(message))
            if prepared_messages:
                request_snapshot = tuple(prepared_messages)
        if normalized_reasoning:
            reasoning_segments = tuple(
                LLMReasoningSegment(
                    type=segment["type"],
                    text=segment["text"],
                )
                for segment in normalized_reasoning
            )

        error_template = exception_to_mcp_error(exc)["error"]

        if not message_text.strip():
            fallback_message = self._format_validation_fallback_message(error_template)
            message_text = fallback_message
            details_payload = error_template.get("details")
            if isinstance(details_payload, Mapping):
                details_payload = dict(details_payload)
            else:
                details_payload = {}
            details_payload["llm_message"] = fallback_message
            error_template["details"] = details_payload

        assistant_tool_calls = [
            prepared.assistant_fragment for prepared in prepared_calls
        ]
        synthetic_calls = [prepared.call for prepared in prepared_calls]
        tool_messages: list[dict[str, Any]] = []
        first_error_payload: dict[str, Any] | None = None

        for prepared in prepared_calls:
            error_payload = self._prepare_tool_payload(
                prepared.call,
                {
                    "ok": False,
                    "error": dict(error_template),
                },
                include_arguments=False,
            )
            arguments = prepared.arguments_for_payload
            if isinstance(arguments, Mapping):
                error_payload["tool_arguments"] = dict(arguments)
            elif arguments is not None:
                error_payload["tool_arguments"] = arguments
            error_payload.setdefault("agent_status", "failed")
            self._emit_tool_result(on_tool_result, error_payload)
            tool_messages.append(self._tool_message(prepared.call, error_payload))
            if first_error_payload is None:
                first_error_payload = error_payload

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": message_text,
        }
        if assistant_tool_calls:
            assistant_message["tool_calls"] = assistant_tool_calls
        if normalized_reasoning:
            assistant_message["reasoning"] = normalized_reasoning
        conversation.append(assistant_message)

        if tool_messages:
            conversation.extend(tool_messages)
        else:
            fallback_payload: dict[str, Any] = {
                "ok": False,
                "error": dict(error_template),
                "tool_name": "invalid_tool_call",
                "tool_call_id": "tool_call_0",
                "call_id": "tool_call_0",
                "agent_status": "failed",
            }
            self._emit_tool_result(on_tool_result, fallback_payload)
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": fallback_payload["tool_call_id"],
                    "name": fallback_payload["tool_name"],
                    "content": json.dumps(fallback_payload, ensure_ascii=False, default=str),
                }
            )
            first_error_payload = fallback_payload

        synthetic_response = LLMResponse(
            content=message_text,
            tool_calls=tuple(synthetic_calls),
            request_messages=request_snapshot,
            reasoning=reasoning_segments,
        )
        return synthetic_response, first_error_payload

    def _prepare_invalid_tool_calls(
        self, raw_calls: Sequence[Any] | None
    ) -> list[_ValidationToolCallPayload]:
        if not isinstance(raw_calls, Sequence) or isinstance(
            raw_calls, (str, bytes, bytearray)
        ):
            return []
        prepared: list[_ValidationToolCallPayload] = []
        for index, entry in enumerate(raw_calls):
            if not isinstance(entry, Mapping):
                continue
            function = entry.get("function")
            if not isinstance(function, Mapping):
                continue
            name = function.get("name")
            if not name:
                continue
            arguments_text, arguments_for_payload = self._normalise_tool_arguments_from_error(
                function.get("arguments")
            )
            call_id = entry.get("id") or entry.get("tool_call_id") or f"tool_call_{index}"
            call_id_str = str(call_id)
            assistant_fragment = {
                "id": call_id_str,
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": arguments_text,
                },
            }
            if isinstance(arguments_for_payload, Mapping):
                call_arguments: Mapping[str, Any] = dict(arguments_for_payload)
            else:
                call_arguments = {}
            prepared.append(
                _ValidationToolCallPayload(
                    call=LLMToolCall(
                        id=call_id_str,
                        name=str(name),
                        arguments=call_arguments,
                    ),
                    assistant_fragment=assistant_fragment,
                    arguments_for_payload=(
                        dict(arguments_for_payload)
                        if isinstance(arguments_for_payload, Mapping)
                        else arguments_for_payload
                    ),
                )
            )
        return prepared

    def _normalise_tool_arguments_from_error(self, raw: Any) -> tuple[str, Any | None]:
        if isinstance(raw, str):
            text = raw.strip() or "{}"
            parsed = self._safe_json_loads(text)
            if isinstance(parsed, Mapping):
                return text, dict(parsed)
            return text, parsed
        if isinstance(raw, Mapping):
            prepared = dict(raw)
            return self._format_tool_arguments(prepared), prepared
        if raw is None:
            return "{}", None
        try:
            text = json.dumps(raw, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return "{}", None
        parsed = self._safe_json_loads(text)
        if isinstance(parsed, Mapping):
            return text, dict(parsed)
        return text, parsed

    @staticmethod
    def _safe_json_loads(text: str) -> Any:
        try:
            return json.loads(text)
        except Exception:
            return text

    @staticmethod
    def _emit_tool_result(
        callback: Callable[[Mapping[str, Any]], None] | None,
        payload: Mapping[str, Any],
    ) -> None:
        """Deliver intermediate MCP *payload* to the provided *callback*."""

        if callback is None:
            return
        try:
            prepared = dict(payload) if isinstance(payload, Mapping) else {"value": payload}
            callback(prepared)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                "AGENT_TOOL_STREAM_ERROR",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
            )

    def _prepare_consecutive_tool_error_result(
        self,
        payload: Mapping[str, Any] | None,
        consecutive_errors: int,
        *,
        reasoning_segments: Sequence[LLMReasoningSegment] | None = None,
    ) -> dict[str, Any]:
        """Return final result payload when tool failures exceed the cap."""

        prepared: dict[str, Any] = {}
        if isinstance(payload, Mapping):
            prepared.update(payload)
        else:  # pragma: no cover - defensive guard
            prepared["error"] = {
                "type": "ConsecutiveToolError",
                "message": "Tool call failed repeatedly",
                "details": payload,
            }
        prepared["ok"] = False
        stop_reason: dict[str, Any] = {
            "type": "consecutive_tool_errors",
            "count": consecutive_errors,
        }
        if self._max_consecutive_tool_errors is not None:
            stop_reason["max_consecutive_tool_errors"] = (
                self._max_consecutive_tool_errors
            )
        prepared["agent_stop_reason"] = stop_reason
        normalized_reasoning = normalise_reasoning_segments(reasoning_segments)
        if normalized_reasoning:
            prepared.setdefault("reasoning", normalized_reasoning)
        return prepared

    def _success_result(
        self,
        response: LLMResponse,
        tool_results: Sequence[Mapping[str, Any]] | None,
        *,
        reasoning_segments: Sequence[LLMReasoningSegment] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "error": None,
            "result": response.content.strip(),
        }
        segments: Sequence[LLMReasoningSegment]
        if reasoning_segments:
            segments = reasoning_segments
        else:
            segments = response.reasoning
        normalized_reasoning = normalise_reasoning_segments(segments)
        if normalized_reasoning:
            payload["reasoning"] = normalized_reasoning
        if tool_results:
            payload["tool_results"] = [dict(result) for result in tool_results]
        return payload

    def _normalise_tool_arguments(self, call: LLMToolCall) -> Any:
        """Return JSON-compatible representation of tool arguments."""

        try:
            return json.loads(self._format_tool_arguments(call.arguments))
        except (TypeError, ValueError, json.JSONDecodeError):
            if isinstance(call.arguments, Mapping):
                return dict(call.arguments)
            return call.arguments

    def _prepare_tool_payload(
        self,
        call: LLMToolCall,
        payload: Mapping[str, Any],
        *,
        include_arguments: bool = True,
    ) -> dict[str, Any]:
        """Attach identifying metadata for *call* to the tool *payload*."""

        prepared = dict(payload)
        prepared.setdefault("tool_name", call.name)
        prepared.setdefault("tool_call_id", call.id)
        prepared.setdefault("call_id", call.id)
        if include_arguments and "tool_arguments" not in prepared:
            prepared["tool_arguments"] = self._normalise_tool_arguments(call)
        return prepared

    def _assistant_message(self, response: LLMResponse) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
        }
        reasoning_segments = normalise_reasoning_segments(response.reasoning)
        if reasoning_segments:
            message["reasoning"] = reasoning_segments
        if response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": self._format_tool_arguments(call.arguments),
                    },
                }
                for call in response.tool_calls
            ]
        return message

    def _tool_message(self, call: LLMToolCall, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": self._serialise_tool_payload(payload),
        }

    @staticmethod
    def _format_tool_arguments(arguments: Mapping[str, Any]) -> str:
        return json.dumps(arguments, ensure_ascii=False, default=str)

    @staticmethod
    def _serialise_tool_payload(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)


@dataclass(slots=True)
class _ValidationToolCallPayload:
    """Prepared representation of invalid tool calls returned by the LLM."""

    call: LLMToolCall
    assistant_fragment: dict[str, Any]
    arguments_for_payload: Any | None


@dataclass(slots=True)
class _AgentLoopStep:
    """Container describing the outcome of a single agent iteration."""

    response: LLMResponse
    tool_error: Mapping[str, Any] | None
    batch_results: list[Mapping[str, Any]]
    final_result: dict[str, Any] | None


class AgentLoopRunner:
    """Stateful helper executing :class:`LocalAgent` iterations."""

    def __init__(
        self,
        *,
        agent: LocalAgent,
        conversation: list[Mapping[str, Any]],
        cancellation: CancellationEvent | None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None,
        on_llm_step: Callable[[Mapping[str, Any]], None] | None,
    ) -> None:
        self._agent = agent
        self._conversation = conversation
        self._cancellation = cancellation
        self._on_tool_result = on_tool_result
        self._on_llm_step = on_llm_step
        self._accumulated_results: list[Mapping[str, Any]] = []
        self._last_response: LLMResponse | None = None
        self._step = 0
        self._consecutive_tool_errors = 0
        self._reasoning_trace: list[LLMReasoningSegment] = []

    async def run(self) -> dict[str, Any]:
        """Execute the main loop until completion or enforced abort."""

        while not self.should_abort():
            self._agent._raise_if_cancelled(self._cancellation)
            step_outcome = await self.step_llm()
            final = self._finalise_step(step_outcome)
            if final is not None:
                return final
        return self._abort_due_to_step_limit()

    async def step_llm(self) -> _AgentLoopStep:
        """Perform a single LLM interaction."""

        try:
            response = await self._agent._llm.respond_async(
                self._conversation,
                cancellation=self._cancellation,
            )
        except ToolValidationError as exc:
            return self._handle_validation_error(exc)
        return await self.handle_tool_batch(response)

    async def handle_tool_batch(self, response: LLMResponse) -> _AgentLoopStep:
        """Execute MCP tools requested by *response* when present."""

        self._register_response(response)
        self._conversation.append(self._agent._assistant_message(response))
        self._advance_step(response)
        if not response.tool_calls:
            return _AgentLoopStep(
                response=response,
                tool_error=None,
                batch_results=[],
                final_result=self._agent._success_result(
                    response,
                    self._accumulated_results,
                    reasoning_segments=self._reasoning_trace,
                ),
            )
        (
            tool_messages,
            tool_error,
            batch_results,
        ) = await self._agent._execute_tool_calls_core(
            response.tool_calls,
            cancellation=self._cancellation,
            on_tool_result=self._on_tool_result,
        )
        self._conversation.extend(tool_messages)
        return _AgentLoopStep(
            response=response,
            tool_error=tool_error,
            batch_results=batch_results,
            final_result=None,
        )

    def should_abort(self) -> bool:
        """Return ``True`` when the configured step cap has been reached."""

        return (
            self._agent._max_thought_steps is not None
            and self._step >= self._agent._max_thought_steps
        )

    def _handle_validation_error(self, exc: ToolValidationError) -> _AgentLoopStep:
        response, tool_error = self._agent._handle_tool_validation_error(
            exc,
            self._conversation,
            on_tool_result=self._on_tool_result,
        )
        self._register_response(response)
        self._advance_step(response)
        return _AgentLoopStep(
            response=response,
            tool_error=tool_error,
            batch_results=[],
            final_result=None,
        )

    def _register_response(self, response: LLMResponse) -> None:
        self._last_response = response
        self._agent._record_request_messages(response)
        if response.reasoning:
            self._reasoning_trace.extend(response.reasoning)

    def _advance_step(self, response: LLMResponse) -> None:
        self._step += 1
        detail_payload = self._agent._log_step(self._step, response)
        if self._on_llm_step is not None and isinstance(detail_payload, Mapping):
            try:
                self._on_llm_step(detail_payload)
            except Exception as exc:  # pragma: no cover - defensive
                log_event(
                    "AGENT_STEP_STREAM_ERROR",
                    {
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    },
                )

    def _finalise_step(self, outcome: _AgentLoopStep) -> dict[str, Any] | None:
        self._accumulated_results.extend(outcome.batch_results)
        if outcome.final_result is not None:
            return outcome.final_result
        if outcome.tool_error is None:
            self._consecutive_tool_errors = 0
            self._agent._raise_if_cancelled(self._cancellation)
            return None
        self._consecutive_tool_errors += 1
        if self._should_stop_due_to_tool_errors():
            return self._abort_due_to_consecutive_tool_errors(outcome.tool_error)
        self._agent._raise_if_cancelled(self._cancellation)
        return None

    def _should_stop_due_to_tool_errors(self) -> bool:
        limit = self._agent._max_consecutive_tool_errors
        return limit is not None and self._consecutive_tool_errors >= limit

    def _abort_due_to_consecutive_tool_errors(
        self, payload: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        abort_payload: dict[str, Any] = {
            "reason": "tool-error-limit",
            "consecutive_errors": self._consecutive_tool_errors,
        }
        limit = self._agent._max_consecutive_tool_errors
        if limit is not None:
            abort_payload["max_consecutive_tool_errors"] = limit
        if isinstance(payload, Mapping):
            abort_payload["tool_name"] = payload.get("tool_name")
            abort_payload["tool_call_id"] = payload.get("tool_call_id")
            error_payload = payload.get("error")
            if isinstance(error_payload, Mapping):
                abort_payload["error_type"] = error_payload.get("type")
        log_event("AGENT_ABORTED", abort_payload)
        return self._agent._prepare_consecutive_tool_error_result(
            payload,
            self._consecutive_tool_errors,
            reasoning_segments=self._reasoning_trace,
        )

    def _abort_due_to_step_limit(self) -> dict[str, Any]:
        assert (
            self._agent._max_thought_steps is not None
        ), "step limit abort triggered without a configured limit"
        abort_payload: dict[str, Any] = {
            "reason": "max-steps",
            "max_steps": self._agent._max_thought_steps,
        }
        if self._last_response is not None:
            if self._last_response.content:
                abort_payload["last_message_preview"] = self._agent._preview(
                    self._last_response.content
                )
            if self._last_response.tool_calls:
                abort_payload["last_tool_calls"] = self._agent._summarize_tool_calls(
                    self._last_response.tool_calls
                )
        log_event("AGENT_ABORTED", abort_payload)

        message = (
            "LLM did not finish interaction within allowed steps "
            f"({self._agent._max_thought_steps})"
        )
        if self._last_response is not None:
            if self._last_response.tool_calls:
                call_descriptions: list[str] = []
                for call in self._last_response.tool_calls:
                    call_descriptions.append(
                        f"{call.name} with arguments "
                        f"{self._agent._format_tool_arguments(call.arguments)}"
                    )
                joined = "; ".join(call_descriptions)
                message += f". Last response requested: {joined}"
            elif self._last_response.content:
                message += (
                    f". Last message: {self._last_response.content.strip()}"
                )
        error = ToolValidationError(message)
        if self._last_response is not None:
            if self._last_response.content:
                error.llm_message = self._last_response.content
            if self._last_response.tool_calls:
                error.llm_tool_calls = [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": self._agent._normalise_tool_arguments(call),
                    }
                    for call in self._last_response.tool_calls
                ]
        if self._accumulated_results:
            error.tool_results = [
                dict(result) for result in self._accumulated_results
            ]
        raise error
