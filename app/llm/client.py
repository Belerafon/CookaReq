"""Client for interacting with an OpenAI-compatible LLM API."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any

from ..settings import LLMSettings
from ..util.cancellation import CancellationEvent, OperationCancelledError
from .context import extract_selected_rids_from_messages
from .harmony import convert_tools_for_harmony
from .logging import log_request, log_response
from .request_builder import LLMRequestBuilder
from .response_parser import LLMResponseParser
from .spec import TOOLS
from .types import LLMReasoningSegment, LLMResponse, LLMToolCall
from .validation import ToolValidationError

# When the backend does not require authentication, the official OpenAI client
# still insists on a non-empty ``api_key``.  Using a harmless placeholder allows
# talking to such endpoints while making it explicit that no real key is
# configured.
NO_API_KEY = "sk-no-key"


class LLMClient:
    """High-level client for LLM operations."""

    _SUPPORTED_MESSAGE_FORMATS = frozenset({"openai-chat", "harmony", "qwen"})

    def __init__(self, settings: LLMSettings) -> None:
        """Initialize client with LLM configuration ``settings``."""
        import openai

        self.settings = settings
        message_format = getattr(settings, "message_format", "openai-chat")
        if message_format not in self._SUPPORTED_MESSAGE_FORMATS:
            raise ValueError(
                "Unsupported LLM message format: "
                f"{message_format}. Configure one of: "
                + ", ".join(sorted(self._SUPPORTED_MESSAGE_FORMATS))
            )
        if not self.settings.base_url:
            raise ValueError("LLM base URL is not configured")
        self._message_format = message_format
        api_key = self.settings.api_key or NO_API_KEY
        self._client = openai.OpenAI(
            base_url=self.settings.base_url,
            api_key=api_key,
            timeout=self.settings.timeout_minutes * 60,
            max_retries=self.settings.max_retries,
        )
        self._request_builder = LLMRequestBuilder(settings, message_format)
        self._response_parser = LLMResponseParser(settings, message_format)

    # ------------------------------------------------------------------
    def check_llm(self) -> dict[str, Any]:
        """Perform a minimal request to verify connectivity."""
        return self._check_llm()

    async def check_llm_async(self) -> dict[str, Any]:
        """Asynchronous counterpart to :meth:`check_llm`."""
        return await asyncio.to_thread(self._check_llm)

    # ------------------------------------------------------------------
    def parse_command(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Interpret *text* into an assistant reply with optional tool calls."""
        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        return self.respond(conversation, cancellation=cancellation)

    async def parse_command_async(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Asynchronous counterpart to :meth:`parse_command`."""
        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        return await self.respond_async(conversation, cancellation=cancellation)

    # ------------------------------------------------------------------
    def respond(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Send the full *conversation* to the model and return its reply."""
        return self._respond(list(conversation or []), cancellation=cancellation)

    async def respond_async(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Asynchronous counterpart to :meth:`respond`."""
        return await asyncio.to_thread(
            self._respond,
            list(conversation or []),
            cancellation=cancellation,
        )

    # ------------------------------------------------------------------
    def _check_llm(self) -> dict[str, Any]:
        if self._message_format == "harmony":
            return self._check_llm_harmony()
        return self._check_llm_chat()

    def _check_llm_chat(self) -> dict[str, Any]:
        request_args = self._request_builder.build_raw_request_args(
            [{"role": "user", "content": "ping"}],
            temperature=self._request_builder.resolve_temperature(),
        )
        start = time.monotonic()
        log_request(request_args)
        try:
            self._chat_completion(**request_args)
        except Exception as exc:  # pragma: no cover - network errors
            payload = {
                "error": {"type": type(exc).__name__, "message": str(exc)}
            }
            log_response(payload, start_time=start)
            return {"ok": False, **payload}
        log_response({"ok": True}, start_time=start)
        return {"ok": True}

    def _check_llm_harmony(self) -> dict[str, Any]:
        prompt = self._request_builder.build_harmony_prompt(
            [{"role": "user", "content": "ping"}]
        )
        request_args = {
            "model": self.settings.model,
            "input": prompt.prompt,
            "tools": convert_tools_for_harmony(TOOLS),
            "reasoning": {"effort": "high"},
        }
        temperature = self._request_builder.resolve_temperature()
        if temperature is not None:
            request_args["temperature"] = temperature
        start = time.monotonic()
        log_request(request_args)
        try:
            self._client.responses.create(**request_args)
        except Exception as exc:  # pragma: no cover - network errors
            error_payload: dict[str, Any] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            hint = self._describe_harmony_check_error(exc)
            if hint:
                error_payload["hint"] = hint
            log_response({"error": error_payload}, start_time=start)
            return {"ok": False, "error": error_payload}
        log_response({"ok": True}, start_time=start)
        return {"ok": True}

    # ------------------------------------------------------------------
    def _respond(
        self,
        conversation: Sequence[Mapping[str, Any]],
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        if self._message_format == "harmony":
            return self._respond_harmony(conversation, cancellation=cancellation)
        return self._respond_chat(conversation, cancellation=cancellation)

    def _respond_chat(
        self,
        conversation: Sequence[Mapping[str, Any]],
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        temperature = self._request_builder.resolve_temperature()
        use_stream = bool(cancellation) or self.settings.stream
        prepared = self._request_builder.build_chat_request(
            conversation,
            tools=TOOLS,
            stream=use_stream,
            temperature=temperature,
        )
        self._apply_reasoning_defaults(prepared.request_args)
        start = time.monotonic()
        log_request(prepared.request_args)

        llm_message_text = ""
        normalized_tool_calls: list[dict[str, Any]] = []
        raw_tool_calls_payload: list[Any] = []
        parsed_tool_calls: tuple[LLMToolCall, ...] = ()
        reasoning_accumulator: list[dict[str, str]] = []
        reasoning_segments: tuple[LLMReasoningSegment, ...] = ()

        try:
            completion = self._chat_completion(**prepared.request_args)
            if prepared.request_args.get("stream"):
                (
                    message_text,
                    raw_tool_calls_payload,
                    stream_reasoning,
                ) = self._response_parser.consume_stream(
                    completion, cancellation=cancellation
                )
                if stream_reasoning:
                    reasoning_accumulator.extend(stream_reasoning)
            else:
                (
                    message_text,
                    raw_tool_calls_payload,
                    reasoning_entries,
                ) = self._response_parser.parse_chat_completion(completion)
                if reasoning_entries:
                    reasoning_accumulator.extend(reasoning_entries)
            llm_message_text = message_text
            parsed_tool_calls = self._response_parser.parse_tool_calls(
                raw_tool_calls_payload
            )
            parsed_tool_calls = self._apply_tool_call_defaults(
                parsed_tool_calls,
                request_messages=prepared.snapshot,
            )
            normalized_tool_calls = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            default=str,
                        ),
                    },
                }
                for call in parsed_tool_calls
            ]
            reasoning_segments = self._response_parser.finalize_reasoning_segments(
                reasoning_accumulator
            )
            response = LLMResponse(
                content=message_text,
                tool_calls=parsed_tool_calls,
                request_messages=prepared.snapshot,
                reasoning=reasoning_segments,
            )
            if not response.tool_calls and not response.content:
                raise ToolValidationError(
                    "LLM response did not include a tool call or message",
                )
        except OperationCancelledError:
            log_response({"cancelled": True}, start_time=start)
            raise
        except ToolValidationError as exc:
            if not reasoning_segments and reasoning_accumulator:
                reasoning_segments = self._response_parser.finalize_reasoning_segments(
                    reasoning_accumulator
                )
            log_payload: dict[str, Any] = {
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            }
            if llm_message_text:
                log_payload["message"] = llm_message_text
            if normalized_tool_calls:
                log_payload["tool_calls"] = normalized_tool_calls
            if reasoning_segments:
                log_payload["reasoning"] = [
                    {"type": segment.type, "preview": segment.preview()}
                    for segment in reasoning_segments
                ]
            log_response(log_payload, start_time=start)
            if not hasattr(exc, "llm_message"):
                exc.llm_message = llm_message_text
            if not hasattr(exc, "llm_tool_calls"):
                exc.llm_tool_calls = tuple(normalized_tool_calls)
            if prepared.snapshot and not hasattr(exc, "llm_request_messages"):
                exc.llm_request_messages = prepared.snapshot
            if reasoning_segments and not hasattr(exc, "llm_reasoning"):
                exc.llm_reasoning = [
                    {
                        "type": segment.type,
                        "text": segment.text_with_whitespace,
                    }
                    for segment in reasoning_segments
                ]
            raise
        except Exception as exc:  # pragma: no cover - network errors
            log_response(
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                start_time=start,
            )
            raise
        else:
            log_payload: dict[str, Any] = {"message": response.content}
            if response.tool_calls:
                log_payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in response.tool_calls
                ]
            if response.reasoning:
                log_payload["reasoning"] = [
                    {"type": segment.type, "preview": segment.preview()}
                    for segment in response.reasoning
                ]
            log_response(log_payload, start_time=start)
            return LLMResponse(
                content=response.content.strip(),
                tool_calls=response.tool_calls,
                request_messages=prepared.snapshot,
                reasoning=response.reasoning,
            )

    def _apply_reasoning_defaults(self, request_args: dict[str, Any]) -> None:
        """Inject reasoning flags so compatible models emit their thoughts."""
        request_args.pop("reasoning_effort", None)
        raw_extra = request_args.get("extra_body")
        if isinstance(raw_extra, Mapping):
            extra_body: dict[str, Any] = dict(raw_extra)
        else:
            extra_body = {}
        reasoning_block = extra_body.get("reasoning")
        if isinstance(reasoning_block, Mapping):
            reasoning_payload: dict[str, Any] = dict(reasoning_block)
        else:
            reasoning_payload = {}
        reasoning_payload.setdefault("enabled", True)
        reasoning_payload.setdefault("effort", "medium")
        extra_body["reasoning"] = reasoning_payload
        extra_body.setdefault("include_reasoning", True)
        request_args["extra_body"] = extra_body

    def _respond_harmony(
        self,
        conversation: Sequence[Mapping[str, Any]],
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        if cancellation and cancellation.is_set():
            raise OperationCancelledError()

        prompt = self._request_builder.build_harmony_prompt(conversation)
        request_snapshot: tuple[Mapping[str, Any], ...] | None = (
            prompt.snapshot(),
        )
        stream_requested = bool(cancellation) or self.settings.stream
        request_args = {
            "model": self.settings.model,
            "input": prompt.prompt,
            "tools": convert_tools_for_harmony(TOOLS),
            "reasoning": {"effort": "high"},
        }
        temperature = self._request_builder.resolve_temperature()
        if temperature is not None:
            request_args["temperature"] = temperature
        start = time.monotonic()
        log_request(request_args)

        llm_message_text = ""
        normalized_tool_calls: list[dict[str, Any]] = []
        raw_tool_calls_payload: list[Any] = []
        parsed_tool_calls: tuple[LLMToolCall, ...] = ()
        reasoning_segments: tuple[LLMReasoningSegment, ...] = ()

        try:
            if stream_requested:
                completion = self._request_harmony_stream(
                    request_args,
                    cancellation=cancellation,
                )
            else:
                completion = self._client.responses.create(**request_args)
            message_text, raw_tool_calls_payload = self._response_parser.parse_harmony_output(
                completion
            )
            llm_message_text = message_text
            parsed_tool_calls = self._response_parser.parse_tool_calls(
                raw_tool_calls_payload
            )
            parsed_tool_calls = self._apply_tool_call_defaults(
                parsed_tool_calls,
                request_messages=request_snapshot,
            )
            normalized_tool_calls = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            default=str,
                        ),
                    },
                }
                for call in parsed_tool_calls
            ]
            response = LLMResponse(
                content=message_text,
                tool_calls=parsed_tool_calls,
                request_messages=request_snapshot,
            )
            if not response.tool_calls and not response.content:
                raise ToolValidationError(
                    "LLM response did not include a tool call or message",
                )
        except OperationCancelledError:
            log_response({"cancelled": True}, start_time=start)
            raise
        except ToolValidationError as exc:
            log_payload: dict[str, Any] = {
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            }
            if llm_message_text:
                log_payload["message"] = llm_message_text
            if normalized_tool_calls:
                log_payload["tool_calls"] = normalized_tool_calls
            if reasoning_segments:
                log_payload["reasoning"] = [
                    {"type": segment.type, "preview": segment.preview()}
                    for segment in reasoning_segments
                ]
            log_response(log_payload, start_time=start)
            if not hasattr(exc, "llm_message"):
                exc.llm_message = llm_message_text
            if not hasattr(exc, "llm_tool_calls"):
                exc.llm_tool_calls = tuple(normalized_tool_calls)
            if request_snapshot and not hasattr(exc, "llm_request_messages"):
                exc.llm_request_messages = request_snapshot
            if reasoning_segments and not hasattr(exc, "llm_reasoning"):
                exc.llm_reasoning = [
                    {
                        "type": segment.type,
                        "text": segment.text_with_whitespace,
                    }
                    for segment in reasoning_segments
                ]
            raise
        except Exception as exc:  # pragma: no cover - network errors
            log_response(
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                start_time=start,
            )
            raise
        else:
            log_payload: dict[str, Any] = {"message": response.content}
            if response.tool_calls:
                log_payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in response.tool_calls
                ]
            log_response(log_payload, start_time=start)
            return LLMResponse(
                content=response.content.strip(),
                tool_calls=response.tool_calls,
                request_messages=request_snapshot,
                reasoning=reasoning_segments,
            )

    def _apply_tool_call_defaults(
        self,
        tool_calls: Sequence[LLMToolCall],
        *,
        request_messages: Sequence[Mapping[str, Any]] | None,
    ) -> tuple[LLMToolCall, ...]:
        """Fill missing get_requirement arguments using workspace context."""
        if not tool_calls:
            return ()

        selected_rids = extract_selected_rids_from_messages(request_messages)
        if not selected_rids:
            return tuple(tool_calls)

        patched: list[LLMToolCall] = []
        changed = False
        for call in tool_calls:
            if str(call.name) != "get_requirement":
                patched.append(call)
                continue

            arguments = dict(call.arguments)
            rid_value = arguments.get("rid")
            should_patch = False
            if isinstance(rid_value, str):
                should_patch = not rid_value.strip()
            elif isinstance(rid_value, Sequence) and not isinstance(
                rid_value, (str, bytes, bytearray)
            ):
                cleaned = [
                    str(item).strip()
                    for item in rid_value
                    if str(item).strip()
                ]
                if cleaned:
                    arguments["rid"] = cleaned if len(cleaned) > 1 else cleaned[0]
                else:
                    should_patch = True
            elif rid_value is None:
                should_patch = True

            if should_patch:
                arguments["rid"] = (
                    selected_rids
                    if len(selected_rids) > 1
                    else selected_rids[0]
                )
                patched.append(
                    LLMToolCall(id=call.id, name=call.name, arguments=dict(arguments))
                )
                changed = True
            else:
                patched.append(call)

        if not changed:
            return tuple(tool_calls)
        return tuple(patched)

    # ------------------------------------------------------------------
    def _chat_completion(self, **request_args: Any) -> Any:
        """Call the chat completions endpoint with normalized arguments."""
        try:
            return self._client.chat.completions.create(**request_args)
        except TypeError as exc:
            raise TypeError(
                "LLM client rejected provided arguments; "
                "verify that the backend is OpenAI-compatible."
            ) from exc

    def _request_harmony_stream(
        self,
        request_args: Mapping[str, Any],
        *,
        cancellation: CancellationEvent | None,
    ) -> Any:
        cancel_event = cancellation
        closed_by_cancel = False

        def ensure_not_cancelled(stream: Any) -> None:
            nonlocal closed_by_cancel
            if cancel_event is None:
                return
            if cancel_event.wait(timeout=0) or cancel_event.is_set():
                if not closed_by_cancel:
                    closed_by_cancel = True
                    closer = getattr(stream, "close", None)
                    if callable(closer):  # pragma: no cover - defensive
                        with suppress(Exception):
                            closer()
                raise OperationCancelledError()

        stream_manager = self._client.responses.stream(**request_args)
        with stream_manager as stream:
            ensure_not_cancelled(stream)
            for _event in stream:  # pragma: no branch - no per-event handling
                ensure_not_cancelled(stream)
            ensure_not_cancelled(stream)
            return stream.get_final_response()

    def _describe_harmony_check_error(self, exc: Exception) -> str | None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code is None:
            status_code = getattr(exc, "status_code", None)
        if status_code is None:
            parts = []
            if getattr(exc, "args", None):
                parts.extend(str(arg) for arg in exc.args)
            message_text = " ".join(parts) or str(exc)
            lowered = message_text.lower()
            if "404" in message_text and (
                "not found" in lowered or "not_found" in lowered
            ):
                status_code = 404
        if status_code == 404:
            return (
                "Harmony requires support for the OpenAI Responses API. "
                f"The provider at {self.settings.base_url!r} returned 404 Not Found "
                "when /responses was requested. Upgrade the proxy/endpoint to a "
                "Responses-compatible version or switch to the \"OpenAI (legacy)\" "
                "format for incompatible servers."
            )
        return None
