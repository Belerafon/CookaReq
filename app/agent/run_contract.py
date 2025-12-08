"""Structured, deterministic contract for agent run results."""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime
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
    sequence: int | None = None
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
        if self.sequence is not None:
            payload["sequence"] = self.sequence
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
        sequence_value: int | None
        try:
            raw_sequence = payload.get("sequence")
            sequence_value = int(raw_sequence) if raw_sequence is not None else None
        except (TypeError, ValueError):
            sequence_value = None

        return cls(
            call_id=str(call_id_value or ""),
            tool_name=str(tool_name_value or ""),
            status=status,
            sequence=sequence_value,
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
    ) -> str:
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
        return timestamp


def sort_tool_result_snapshots(
    snapshots: Sequence[ToolResultSnapshot],
) -> list[ToolResultSnapshot]:
    """Return snapshots ordered by explicit sequence or original position."""

    ordered = sorted(
        enumerate(snapshots),
        key=lambda pair: (
            0 if pair[1].sequence is not None else 1,
            pair[1].sequence if pair[1].sequence is not None else pair[0],
        ),
    )
    return [snapshot for _, snapshot in ordered]


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
class AgentEvent:
    """Single chronological event of an agent run."""

    kind: Literal[
        "llm_step",
        "reasoning",
        "tool_started",
        "tool_completed",
        "agent_finished",
    ]
    occurred_at: str
    payload: Mapping[str, Any]
    sequence: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "kind": self.kind,
            "occurred_at": self.occurred_at,
            "payload": dict(self.payload),
        }
        if self.sequence is not None:
            payload["sequence"] = self.sequence
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AgentEvent":
        kind = payload.get("kind")
        if kind not in {
            "llm_step",
            "reasoning",
            "tool_started",
            "tool_completed",
            "agent_finished",
        }:
            raise ValueError(f"invalid agent event kind: {kind!r}")
        occurred_at = payload.get("occurred_at")
        if not isinstance(occurred_at, str) or not occurred_at.strip():
            raise ValueError("agent event missing occurred_at")
        payload_value = payload.get("payload")
        mapping: Mapping[str, Any]
        if isinstance(payload_value, Mapping):
            mapping = payload_value
        else:
            mapping = {}
        sequence = payload.get("sequence")
        try:
            sequence_value = int(sequence) if sequence is not None else None
        except (TypeError, ValueError):
            sequence_value = None
        return cls(
            kind=kind,
            occurred_at=occurred_at,
            payload=mapping,
            sequence=sequence_value,
        )


@dataclass(slots=True)
class AgentEventLog:
    """Ordered list of :class:`AgentEvent` objects."""

    events: list[AgentEvent] = field(default_factory=list)

    def append(self, event: AgentEvent) -> None:
        if event.sequence is None:
            event.sequence = len(self.events)
        self.events.append(event)

    def normalise_sequences(self) -> None:
        for index, event in enumerate(self.events):
            if event.sequence is None:
                event.sequence = index

    def to_dict(self) -> dict[str, Any]:
        return {"events": [event.to_dict() for event in self.events]}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AgentEventLog":
        events_payload = payload.get("events")
        events: list[AgentEvent] = []
        if isinstance(events_payload, Sequence) and not isinstance(
            events_payload, (str, bytes, bytearray)
        ):
            for index, entry in enumerate(events_payload):
                if not isinstance(entry, Mapping):
                    continue
                try:
                    event = AgentEvent.from_dict(entry)
                    if event.sequence is None:
                        event.sequence = index
                    events.append(event)
                except Exception:
                    continue
        return cls(events=events)


@dataclass(slots=True)
class AgentRunPayload:
    """Deterministic payload exposed as ``raw_result`` for chat entries."""

    ok: bool
    status: Literal["succeeded", "failed"]
    result_text: str
    events: AgentEventLog = field(default_factory=AgentEventLog)
    tool_results: list[ToolResultSnapshot] = field(default_factory=list)
    llm_trace: LlmTrace = field(default_factory=LlmTrace)
    reasoning: Sequence[Mapping[str, Any]] = field(default_factory=list)
    diagnostic: Mapping[str, Any] | None = None
    error: ToolError | None = None
    tool_schemas: Mapping[str, Any] | None = None
    agent_stop_reason: Mapping[str, Any] | None = None

    def to_dict(self, *, include_diagnostic_event_log: bool = True) -> dict[str, Any]:
        self.events.normalise_sequences()
        payload: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "result": self.result_text,
            "events": self.events.to_dict(),
            "llm_trace": self.llm_trace.to_dict(),
            "reasoning": [dict(segment) for segment in self.reasoning],
        }
        payload["error"] = (
            self.error.to_dict() if self.error is not None else None
        )
        if self.tool_results:
            ordered_snapshots = sort_tool_result_snapshots(self.tool_results)
            payload["tool_results"] = [
                snapshot.to_dict() for snapshot in ordered_snapshots
            ]
        if self.diagnostic is not None:
            diagnostic_payload = dict(self.diagnostic)
            if not include_diagnostic_event_log:
                diagnostic_payload.pop("event_log", None)
            if diagnostic_payload:
                payload["diagnostic"] = diagnostic_payload
        elif include_diagnostic_event_log and self.events.events:
            payload["diagnostic"] = {"event_log": [event.to_dict() for event in self.events.events]}
        if self.tool_schemas is not None:
            payload["tool_schemas"] = dict(self.tool_schemas)
        if self.agent_stop_reason is not None:
            payload["agent_stop_reason"] = dict(self.agent_stop_reason)
        return payload

    def to_history_dict(self) -> dict[str, Any]:
        """Return serialisation without duplicating the event log in diagnostics."""

        return self.to_dict(include_diagnostic_event_log=False)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AgentRunPayload":
        ok = bool(payload.get("ok"))
        status_value = payload.get("status")
        status = "succeeded" if status_value == "succeeded" else "failed"
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
        if tool_results:
            tool_results = sort_tool_result_snapshots(tool_results)
        events_payload = payload.get("events")
        events = (
            AgentEventLog.from_dict(events_payload)
            if isinstance(events_payload, Mapping)
            else AgentEventLog()
        )
        if not events.events:
            diagnostic_payload = payload.get("diagnostic")
            if isinstance(diagnostic_payload, Mapping):
                event_log_payload = diagnostic_payload.get("event_log")
                if isinstance(event_log_payload, Sequence):
                    events = AgentEventLog.from_dict({"events": event_log_payload})
        error_payload = payload.get("error")
        error: ToolError | None = None
        if isinstance(error_payload, Mapping):
            try:
                error = ToolError.from_dict(error_payload)
            except Exception:
                error = None
        llm_trace_payload = payload.get("llm_trace")
        if isinstance(llm_trace_payload, Mapping):
            llm_trace = LlmTrace.from_dict(llm_trace_payload)
        else:
            llm_trace = _llm_trace_from_events(events)
        if not reasoning:
            reasoning = _reasoning_from_events(events)
        if not tool_results:
            tool_results = _tool_results_from_events(events)
        diagnostic_payload = payload.get("diagnostic")
        diagnostic: Mapping[str, Any] | None
        if isinstance(diagnostic_payload, Mapping):
            diagnostic = dict(diagnostic_payload)
        else:
            diagnostic = None
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
        return cls(
            ok=ok,
            status=status,
            result_text=result_text,
            events=events,
            tool_results=tool_results,
            llm_trace=llm_trace,
            reasoning=reasoning,
            diagnostic=diagnostic,
            error=error,
            tool_schemas=tool_schemas,
            agent_stop_reason=agent_stop_reason,
        )


def _llm_trace_from_events(events: AgentEventLog) -> LlmTrace:
    steps: list[LlmStep] = []
    for event in events.events:
        if event.kind != "llm_step":
            continue
        payload = event.payload
        try:
            index = int(payload.get("index", len(steps) + 1))
        except Exception:
            index = len(steps) + 1
        request_payload = payload.get("request")
        request: list[Mapping[str, Any]] = []
        if isinstance(request_payload, Sequence) and not isinstance(
            request_payload, (str, bytes, bytearray)
        ):
            request = [dict(message) for message in request_payload if isinstance(message, Mapping)]
        response_payload = payload.get("response")
        response: Mapping[str, Any]
        if isinstance(response_payload, Mapping):
            response = dict(response_payload)
        else:
            response = {}
        try:
            steps.append(
                LlmStep(
                    index=index,
                    occurred_at=event.occurred_at,
                    request=request,
                    response=response,
                )
            )
        except Exception:
            continue
    return LlmTrace(steps=steps)


def _reasoning_from_events(events: AgentEventLog) -> list[Mapping[str, Any]]:
    segments: list[Mapping[str, Any]] = []
    for event in events.events:
        if event.kind != "reasoning":
            continue
        payload = event.payload
        payload_segments = payload.get("segments")
        if not isinstance(payload_segments, Sequence) or isinstance(
            payload_segments, (str, bytes, bytearray)
        ):
            continue
        for segment in payload_segments:
            if isinstance(segment, Mapping):
                segments.append(dict(segment))
    return segments


def _tool_results_from_events(events: AgentEventLog) -> list[ToolResultSnapshot]:
    snapshots: dict[str, ToolResultSnapshot] = {}
    order: list[str] = []
    for event in events.events:
        if event.kind not in {"tool_started", "tool_completed"}:
            continue
        payload = event.payload
        call_id = payload.get("call_id")
        if not call_id:
            continue
        call_id_str = str(call_id)
        if call_id_str not in snapshots and event.kind == "tool_started":
            tool_name = str(payload.get("tool_name") or "")
            snapshot = ToolResultSnapshot(
                call_id=call_id_str,
                tool_name=tool_name,
                status="running",
                arguments=payload.get("arguments"),
                schema=payload.get("schema") if isinstance(payload.get("schema"), Mapping) else None,
                started_at=event.occurred_at,
                last_observed_at=event.occurred_at,
                events=[
                    ToolTimelineEvent(
                        kind="started", occurred_at=event.occurred_at, message=None
                    )
                ],
            )
            snapshots[call_id_str] = snapshot
            order.append(call_id_str)
        elif call_id_str not in snapshots:
            tool_name = str(payload.get("tool_name") or "")
            snapshots[call_id_str] = ToolResultSnapshot(
                call_id=call_id_str,
                tool_name=tool_name,
                status="pending",
            )
            order.append(call_id_str)
        snapshot = snapshots[call_id_str]
        if event.kind == "tool_completed":
            status_value = payload.get("status")
            if status_value in {"succeeded", "failed", "running", "pending"}:
                snapshot.status = status_value
            result_value = payload.get("result")
            if result_value is not None:
                snapshot.result = result_value
            error_payload = payload.get("error")
            if isinstance(error_payload, Mapping):
                try:
                    snapshot.error = ToolError.from_dict(error_payload)
                except Exception:
                    snapshot.error = None
            metrics_payload = payload.get("metrics")
            if isinstance(metrics_payload, Mapping):
                try:
                    snapshot.metrics = ToolMetrics.from_dict(metrics_payload)
                except Exception:
                    snapshot.metrics = ToolMetrics()
            timeline_kind = "completed" if snapshot.status != "failed" else "failed"
            snapshot.events.append(
                ToolTimelineEvent(
                    kind=timeline_kind, occurred_at=event.occurred_at, message=None
                )
            )
            snapshot.last_observed_at = event.occurred_at
            snapshot.completed_at = event.occurred_at
    return [snapshots[call_id] for call_id in order]


__all__ = [
    "AgentEvent",
    "AgentEventLog",
    "AgentRunPayload",
    "LlmStep",
    "LlmTrace",
    "ToolError",
    "ToolMetrics",
    "ToolResultSnapshot",
    "ToolTimelineEvent",
    "ToolStatus",
    "sort_tool_result_snapshots",
]
