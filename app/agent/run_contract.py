"""Structured, deterministic contract for agent run results."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Literal, Mapping, Sequence

from ..util.time import utc_now_iso


ToolStatus = Literal["pending", "running", "succeeded", "failed"]


@dataclass(slots=True)
class ToolTimelineEvent:
    """Chronological event reported for a tool execution."""

    kind: Literal["started", "update", "completed", "failed"]
    occurred_at: str
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "occurred_at": self.occurred_at,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolTimelineEvent":
        kind = payload.get("kind")
        if kind not in {"started", "update", "completed", "failed"}:
            raise ValueError(f"invalid tool event kind: {kind!r}")
        occurred_at = payload.get("occurred_at")
        if not isinstance(occurred_at, str) or not occurred_at.strip():
            raise ValueError("tool event is missing occurred_at timestamp")
        message = payload.get("message")
        if message is not None and not isinstance(message, str):
            message = str(message)
        return cls(kind=kind, occurred_at=occurred_at, message=message)


@dataclass(slots=True)
class ToolMetrics:
    """Normalised tool metrics exposed to the UI."""

    duration_seconds: float | None = None
    cost: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.duration_seconds is not None:
            payload["duration_seconds"] = self.duration_seconds
        if self.cost is not None:
            payload["cost"] = dict(self.cost)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolMetrics":
        duration_value = payload.get("duration_seconds")
        duration = (
            float(duration_value)
            if isinstance(duration_value, (int, float))
            else None
        )
        cost_payload = payload.get("cost")
        cost: Mapping[str, Any] | None
        if isinstance(cost_payload, Mapping):
            cost = dict(cost_payload)
        else:
            cost = None
        return cls(duration_seconds=duration, cost=cost)


@dataclass(slots=True)
class ToolError:
    """Structured tool failure payload."""

    message: str
    code: Any | None = None
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": self.message}
        if self.code is not None:
            payload["code"] = self.code
        if self.details is not None:
            payload["details"] = dict(self.details)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolError":
        message_raw = payload.get("message")
        message = str(message_raw) if message_raw is not None else ""
        if not message:
            raise ValueError("tool error payload is missing message")
        code = payload.get("code")
        details_payload = payload.get("details")
        details: Mapping[str, Any] | None
        if isinstance(details_payload, Mapping):
            details = dict(details_payload)
        else:
            details = None
        return cls(message=message, code=code, details=details)


@dataclass(slots=True)
class ToolResultSnapshot:
    """State of a tool call exposed to the UI and persisted in history."""

    call_id: str
    tool_name: str
    status: ToolStatus
    arguments: Any | None = None
    result: Any | None = None
    error: ToolError | None = None
    events: list[ToolTimelineEvent] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    last_observed_at: str | None = None
    metrics: ToolMetrics = field(default_factory=ToolMetrics)
    schema: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        arguments_payload: Any
        if self.arguments is None:
            arguments_payload = {}
        elif isinstance(self.arguments, Mapping):
            arguments_payload = dict(self.arguments)
        else:
            arguments_payload = self.arguments
        payload: dict[str, Any] = {
            "tool_name": self.tool_name,
            "tool_arguments": arguments_payload,
            "tool_call_id": self.call_id,
            "call_id": self.call_id,
            "status": self.status,
            "agent_status": self._agent_status_label(),
            "ok": self.status == "succeeded",
        }
        payload["error"] = (
            self.error.to_dict() if self.error is not None else None
        )
        if self.result is not None:
            payload["result"] = self.result
        if arguments_payload is not self.arguments and self.arguments is not None:
            payload["arguments"] = self.arguments
        if self.events:
            payload["events"] = [event.to_dict() for event in self.events]
        if self.started_at is not None:
            payload["started_at"] = self.started_at
        if self.completed_at is not None:
            payload["completed_at"] = self.completed_at
        if self.last_observed_at is not None:
            payload["last_observed_at"] = self.last_observed_at
        metrics_payload = self.metrics.to_dict()
        if metrics_payload:
            payload["metrics"] = metrics_payload
        if self.schema is not None:
            payload["schema"] = dict(self.schema)
        return payload

    def _agent_status_label(self) -> str:
        match self.status:
            case "succeeded":
                return "completed"
            case "failed":
                return "failed"
            case "running":
                return "running"
            case _:
                return "pending"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolResultSnapshot":
        status = payload.get("status")
        if status not in {"pending", "running", "succeeded", "failed"}:
            ok_flag = payload.get("ok")
            if ok_flag is True:
                status = "succeeded"
            elif ok_flag is False or payload.get("error") is not None:
                status = "failed"
            else:
                status = "pending"
        events_payload = payload.get("events")
        events: list[ToolTimelineEvent] = []
        if isinstance(events_payload, Sequence):
            for entry in events_payload:
                if not isinstance(entry, Mapping):
                    continue
                try:
                    events.append(ToolTimelineEvent.from_dict(entry))
                except Exception:
                    continue
        error_payload = payload.get("error")
        error: ToolError | None = None
        if isinstance(error_payload, Mapping):
            try:
                error = ToolError.from_dict(error_payload)
            except Exception:
                error = None
        metrics_payload = payload.get("metrics")
        metrics = ToolMetrics()
        if isinstance(metrics_payload, Mapping):
            try:
                metrics = ToolMetrics.from_dict(metrics_payload)
            except Exception:
                metrics = ToolMetrics()
        schema_payload = payload.get("schema")
        schema: Mapping[str, Any] | None = None
        if isinstance(schema_payload, Mapping):
            schema = dict(schema_payload)
        call_id_value = payload.get("call_id") or payload.get("tool_call_id")
        tool_name_value = payload.get("tool_name") or payload.get("name")
        if not tool_name_value:
            raise ValueError("tool snapshot payload missing tool_name")
        arguments_value = payload.get("tool_arguments")
        if arguments_value is None and "arguments" in payload:
            arguments_value = payload.get("arguments")
        return cls(
            call_id=str(call_id_value or ""),
            tool_name=str(tool_name_value or ""),
            status=status,
            arguments=arguments_value,
            result=payload.get("result"),
            error=error,
            events=events,
            started_at=(
                str(payload.get("started_at")) if payload.get("started_at") else None
            ),
            completed_at=(
                str(payload.get("completed_at"))
                if payload.get("completed_at")
                else None
            ),
            last_observed_at=(
                str(payload.get("last_observed_at"))
                if payload.get("last_observed_at")
                else None
            ),
            metrics=metrics,
            schema=schema,
        )

    def mark_event(
        self,
        kind: Literal["started", "update", "completed", "failed"],
        *,
        message: str | None = None,
    ) -> None:
        timestamp = utc_now_iso()
        self.events.append(
            ToolTimelineEvent(kind=kind, occurred_at=timestamp, message=message)
        )
        if kind == "started" and self.started_at is None:
            self.started_at = timestamp
        self.last_observed_at = timestamp
        if kind in {"completed", "failed"}:
            self.completed_at = timestamp
            if self.started_at is not None:
                duration = _seconds_between(self.started_at, timestamp)
                if duration is not None:
                    self.metrics.duration_seconds = duration


def _seconds_between(start_iso: str, end_iso: str) -> float | None:
    from datetime import datetime

    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = end - start
    total = delta.total_seconds()
    return total if total >= 0 else None


@dataclass(slots=True)
class LlmStep:
    """Canonical representation of a single LLM step."""

    index: int
    occurred_at: str
    request: Sequence[Mapping[str, Any]]
    response: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "occurred_at": self.occurred_at,
            "request": [dict(message) for message in self.request],
            "response": dict(self.response),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LlmStep":
        index_value = payload.get("index")
        if not isinstance(index_value, (int, float)):
            raise ValueError("llm step payload is missing numeric index")
        occurred_at = payload.get("occurred_at")
        if not isinstance(occurred_at, str) or not occurred_at.strip():
            raise ValueError("llm step payload missing occurred_at")
        request_payload = payload.get("request")
        if isinstance(request_payload, Sequence) and not isinstance(
            request_payload, (str, bytes, bytearray)
        ):
            request = [dict(message) for message in request_payload if isinstance(message, Mapping)]
        else:
            request = []
        response_payload = payload.get("response")
        response = dict(response_payload) if isinstance(response_payload, Mapping) else {}
        return cls(
            index=int(index_value),
            occurred_at=occurred_at,
            request=request,
            response=response,
        )


@dataclass(slots=True)
class LlmTrace:
    """Collection of ordered LLM steps captured during an agent run."""

    steps: list[LlmStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [step.to_dict() for step in self.steps]}

    def append(
        self,
        *,
        index: int,
        request: Sequence[Mapping[str, Any]],
        response: Mapping[str, Any],
    ) -> LlmStep:
        step = LlmStep(
            index=index,
            occurred_at=utc_now_iso(),
            request=[dict(message) for message in request],
            response=dict(response),
        )
        self.steps.append(step)
        return step

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LlmTrace":
        steps_payload = payload.get("steps")
        steps: list[LlmStep] = []
        if isinstance(steps_payload, Sequence) and not isinstance(
            steps_payload, (str, bytes, bytearray)
        ):
            for entry in steps_payload:
                if not isinstance(entry, Mapping):
                    continue
                try:
                    steps.append(LlmStep.from_dict(entry))
                except Exception:
                    continue
        return cls(steps=steps)


@dataclass(slots=True)
class AgentRunPayload:
    """Deterministic payload exposed as ``raw_result`` for chat entries."""

    ok: bool
    status: Literal["succeeded", "failed"]
    result_text: str
    reasoning: Sequence[Mapping[str, Any]]
    tool_results: list[ToolResultSnapshot]
    llm_trace: LlmTrace
    error: ToolError | None = None
    diagnostic: Mapping[str, Any] | None = None
    tool_schemas: Mapping[str, Any] | None = None
    last_tool: ToolResultSnapshot | None = None
    agent_stop_reason: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "result": self.result_text,
            "llm_trace": self.llm_trace.to_dict(),
            "reasoning": [dict(segment) for segment in self.reasoning],
        }
        payload["error"] = (
            self.error.to_dict() if self.error is not None else None
        )
        if self.tool_results:
            payload["tool_results"] = [
                snapshot.to_dict() for snapshot in self.tool_results
            ]
        if self.diagnostic is not None:
            payload["diagnostic"] = dict(self.diagnostic)
        if self.tool_schemas is not None:
            payload["tool_schemas"] = dict(self.tool_schemas)
        if self.agent_stop_reason is not None:
            payload["agent_stop_reason"] = dict(self.agent_stop_reason)
        if self.last_tool is not None:
            last_tool_payload = self.last_tool.to_dict()
            payload["last_tool"] = last_tool_payload
            for key in ("tool_name", "tool_call_id", "call_id", "agent_status"):
                value = last_tool_payload.get(key)
                if value is not None:
                    payload[key] = value
            if "tool_arguments" in last_tool_payload:
                payload["tool_arguments"] = last_tool_payload["tool_arguments"]
            if not self.ok and "result" in last_tool_payload:
                payload["tool_result"] = last_tool_payload["result"]
            if payload.get("error") is None and "error" in last_tool_payload:
                payload["error"] = last_tool_payload["error"]
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AgentRunPayload":
        ok = bool(payload.get("ok"))
        status_value = payload.get("status")
        status = "succeeded" if status_value == "succeeded" else "failed"
        error_payload_raw = payload.get("error")
        result_value = payload.get("result")
        if isinstance(result_value, str):
            result_text = result_value
        elif result_value is not None:
            try:
                result_text = json.dumps(result_value, ensure_ascii=False)
            except (TypeError, ValueError):
                result_text = str(result_value)
        else:
            result_text = ""
        reasoning_payload = payload.get("reasoning")
        reasoning: list[Mapping[str, Any]] = []
        if isinstance(reasoning_payload, Sequence) and not isinstance(
            reasoning_payload, (str, bytes, bytearray)
        ):
            for segment in reasoning_payload:
                if isinstance(segment, Mapping):
                    reasoning.append(dict(segment))
        tool_results_payload = payload.get("tool_results")
        tool_results: list[ToolResultSnapshot] = []
        if isinstance(tool_results_payload, Sequence) and not isinstance(
            tool_results_payload, (str, bytes, bytearray)
        ):
            for entry in tool_results_payload:
                if not isinstance(entry, Mapping):
                    continue
                try:
                    tool_results.append(ToolResultSnapshot.from_dict(entry))
                except Exception:
                    continue
        llm_trace_payload = payload.get("llm_trace")
        llm_trace = (
            LlmTrace.from_dict(llm_trace_payload)
            if isinstance(llm_trace_payload, Mapping)
            else LlmTrace()
        )
        error_payload = error_payload_raw
        error: ToolError | None = None
        if isinstance(error_payload, Mapping):
            try:
                error = ToolError.from_dict(error_payload)
            except Exception:
                error = None
            if not result_text:
                details_payload = error_payload.get("details")
                if isinstance(details_payload, Mapping):
                    message_candidate = details_payload.get("llm_message")
                    if isinstance(message_candidate, str) and message_candidate.strip():
                        result_text = message_candidate
                if not result_text:
                    message_candidate = error_payload.get("message")
                    if isinstance(message_candidate, str):
                        result_text = message_candidate
        diagnostic_payload = payload.get("diagnostic")
        diagnostic: Mapping[str, Any] | None
        if isinstance(diagnostic_payload, Mapping):
            diagnostic = dict(diagnostic_payload)
        else:
            diagnostic = None
        if not llm_trace.steps and isinstance(diagnostic, Mapping):
            request_entries = diagnostic.get("llm_requests")
            if isinstance(request_entries, Sequence):
                for index, entry in enumerate(request_entries, 1):
                    if not isinstance(entry, Mapping):
                        continue
                    messages_payload = entry.get("messages")
                    if not isinstance(messages_payload, Sequence):
                        continue
                    request_messages: list[Mapping[str, Any]] = []
                    for message in messages_payload:
                        if isinstance(message, Mapping):
                            request_messages.append(dict(message))
                    if not request_messages:
                        continue
                    step_value = entry.get("step")
                    try:
                        step_index = int(step_value)
                    except (TypeError, ValueError):
                        step_index = index
                    llm_trace.steps.append(
                        LlmStep(
                            index=step_index,
                            occurred_at=utc_now_iso(),
                            request=tuple(request_messages),
                            response={},
                        )
                    )
        planned_call_entries: list[dict[str, Any]] = []
        details_source: Mapping[str, Any] | None = None
        if isinstance(error_payload_raw, Mapping):
            details_candidate = error_payload_raw.get("details")
            if isinstance(details_candidate, Mapping):
                details_source = details_candidate
        elif isinstance(diagnostic, Mapping):
            possible_error = diagnostic.get("error")
            if isinstance(possible_error, Mapping):
                details_candidate = possible_error.get("details")
                if isinstance(details_candidate, Mapping):
                    details_source = details_candidate
        if details_source is not None:
            raw_calls = details_source.get("llm_tool_calls")
            if isinstance(raw_calls, Sequence):
                for entry in raw_calls:
                    if not isinstance(entry, Mapping):
                        continue
                    fragment = dict(entry)
                    function_payload = fragment.get("function")
                    arguments_value: Any = {}
                    name_value = ""
                    if isinstance(function_payload, Mapping):
                        name_value = str(function_payload.get("name") or "")
                        arguments_value = function_payload.get("arguments")
                    if not name_value and isinstance(fragment.get("name"), str):
                        name_value = fragment.get("name")
                    if isinstance(arguments_value, Mapping):
                        arguments_value = dict(arguments_value)
                    planned_call_entries.append(
                        {
                            "id": str(fragment.get("id") or ""),
                            "type": "function",
                            "function": {
                                "name": name_value,
                                "arguments": arguments_value,
                            },
                        }
                    )
        if planned_call_entries:
            if llm_trace.steps:
                last_step = llm_trace.steps[-1]
                response_payload = dict(last_step.response)
                response_payload["tool_calls"] = planned_call_entries
                last_step.response = response_payload
            else:
                llm_trace.steps.append(
                    LlmStep(
                        index=1,
                        occurred_at=utc_now_iso(),
                        request=(),
                        response={"tool_calls": planned_call_entries},
                    )
                )
        tool_schemas_payload = payload.get("tool_schemas")
        tool_schemas: Mapping[str, Any] | None
        if isinstance(tool_schemas_payload, Mapping):
            tool_schemas = dict(tool_schemas_payload)
        else:
            tool_schemas = None
        agent_stop_payload = payload.get("agent_stop_reason")
        agent_stop_reason: Mapping[str, Any] | None
        if isinstance(agent_stop_payload, Mapping):
            agent_stop_reason = dict(agent_stop_payload)
        else:
            agent_stop_reason = None
        last_tool_payload = payload.get("last_tool")
        last_tool: ToolResultSnapshot | None = None
        if isinstance(last_tool_payload, Mapping):
            try:
                last_tool = ToolResultSnapshot.from_dict(last_tool_payload)
            except Exception:
                last_tool = None
        if last_tool is None:
            if tool_results:
                last_tool = tool_results[-1]
            else:
                tool_name_value = payload.get("tool_name")
                call_id_value = payload.get("call_id") or payload.get("tool_call_id")
                if tool_name_value:
                    synthetic_payload: dict[str, Any] = {
                        "tool_name": tool_name_value,
                        "call_id": call_id_value,
                        "tool_call_id": call_id_value,
                        "status": payload.get("status")
                        if payload.get("status") in {"pending", "running", "succeeded", "failed"}
                        else ("succeeded" if ok else "failed"),
                        "tool_arguments": payload.get("tool_arguments"),
                        "result": payload.get("tool_result", payload.get("result")),
                        "error": payload.get("error"),
                    }
                    try:
                        synthetic_snapshot = ToolResultSnapshot.from_dict(
                            synthetic_payload
                        )
                    except Exception:
                        synthetic_snapshot = None
                    if synthetic_snapshot is not None:
                        last_tool = synthetic_snapshot
                        tool_results.append(synthetic_snapshot)
        return cls(
            ok=ok,
            status=status,
            result_text=result_text,
            reasoning=reasoning,
            tool_results=tool_results,
            llm_trace=llm_trace,
            error=error,
            diagnostic=diagnostic,
            tool_schemas=tool_schemas,
            last_tool=last_tool,
            agent_stop_reason=agent_stop_reason,
        )


__all__ = [
    "AgentRunPayload",
    "LlmStep",
    "LlmTrace",
    "ToolError",
    "ToolMetrics",
    "ToolResultSnapshot",
    "ToolTimelineEvent",
    "ToolStatus",
]
