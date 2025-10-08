"""Formatting helpers for MCP tool call summaries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import json

from ...i18n import _
from ..text import normalize_for_display
from .time_formatting import format_entry_timestamp, parse_iso_timestamp


@dataclass(frozen=True)
class ToolCallSummary:
    """Human-friendly description of an MCP tool exchange."""

    index: int
    tool_name: str
    status: str
    bullet_lines: tuple[str, ...]
    started_at: str | None = None
    completed_at: str | None = None
    last_observed_at: str | None = None
    raw_payload: Any | None = None
    duration: float | None = None
    cost: str | None = None
    error_message: str | None = None
    arguments: Any | None = None
    category: Literal["tool", "validation_guard"] = "tool"


@dataclass(frozen=True)
class ValidationGuardMetadata:
    """Structured details extracted from a validation guard payload."""

    reason: str | None
    llm_message: str | None
    code: str | None
    details: Mapping[str, Any] | None


def summarize_tool_results(
    tool_results: Sequence[Any] | None,
) -> tuple[ToolCallSummary, ...]:
    """Generate summaries for tool payloads returned by the agent."""

    from .history_utils import history_json_safe, sort_tool_payloads

    summaries: list[ToolCallSummary] = []
    if not tool_results:
        return tuple(summaries)

    ordered_payloads = sort_tool_payloads(tool_results)
    for index, payload in enumerate(ordered_payloads, start=1):
        if not isinstance(payload, Mapping):
            continue
        summary = summarize_tool_payload(index, payload)
        if summary is None:
            continue
        safe_payload = history_json_safe(payload)
        summaries.append(replace(summary, raw_payload=safe_payload))
    return tuple(summaries)


def _normalise_timestamp(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        formatted = format_entry_timestamp(text)
        if formatted:
            return normalize_for_display(formatted)
        return normalize_for_display(text)
    return None


def _normalise_optional_string(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return normalize_for_display(text)
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _extract_duration_seconds(payload: Mapping[str, Any]) -> float | None:
    for key in (
        "duration_seconds",
        "duration_secs",
        "duration_sec",
        "duration_s",
        "duration",
    ):
        candidate = _coerce_float(payload.get(key))
        if candidate is not None and candidate >= 0:
            return candidate
    duration_ms = _coerce_float(payload.get("duration_ms"))
    if duration_ms is not None and duration_ms >= 0:
        return duration_ms / 1000.0
    start_raw = (
        payload.get("started_at")
        or payload.get("first_observed_at")
        or payload.get("observed_at")
    )
    end_raw = (
        payload.get("completed_at")
        or payload.get("last_observed_at")
        or payload.get("observed_at")
    )
    start = parse_iso_timestamp(start_raw)
    end = parse_iso_timestamp(end_raw)
    if start and end:
        delta = (end - start).total_seconds()
        if delta >= 0:
            return delta
    return None


def _format_cost_value(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return normalize_for_display(f"{value}")
    if isinstance(value, str):
        text = value.strip()
        if text:
            return normalize_for_display(text)
    return None


def _coerce_cost_text(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in (
            "display",
            "formatted",
            "text",
            "label",
            "value",
            "total",
            "amount",
            "usd",
        ):
            text = _coerce_cost_text(value.get(key))
            if text:
                return text
        return None
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for item in value:
            text = _coerce_cost_text(item)
            if text:
                return text
        return None
    text = _format_cost_value(value)
    if text:
        return text
    if value is not None:
        try:
            return format_value_snippet(value)
        except Exception:  # pragma: no cover - defensive
            return None
    return None


def _extract_cost_text(payload: Mapping[str, Any]) -> str | None:
    for key in ("cost", "usage_cost", "price", "total_cost"):
        if key in payload:
            text = _coerce_cost_text(payload.get(key))
            if text:
                return text
    return None


def _extract_arguments(payload: Mapping[str, Any]) -> Any | None:
    for key in ("tool_arguments", "arguments", "args"):
        if key not in payload:
            continue
        candidate = payload.get(key)
        if candidate is None:
            continue
        from .history_utils import history_json_safe  # local import to avoid cycle

        return history_json_safe(candidate)
    return None


def _derive_error_message(payload: Mapping[str, Any]) -> str | None:
    message = extract_error_message(payload.get("error"))
    if not message:
        extra_message = payload.get("error_message") or payload.get("message")
        if isinstance(extra_message, str):
            text = extra_message.strip()
            if text:
                message = shorten_text(normalize_for_display(text))
    if not message:
        agent_status = payload.get("agent_status")
        if isinstance(agent_status, str):
            status_text = agent_status.strip()
            if status_text:
                prefix, _, remainder = status_text.partition(":")
                if prefix.strip().lower() == "failed":
                    candidate = remainder.strip() or prefix.strip()
                    if candidate:
                        message = shorten_text(normalize_for_display(candidate))
    return message or None


def summarize_tool_payload(
    index: int, payload: Mapping[str, Any]
) -> ToolCallSummary | None:
    if is_validation_guard_payload(payload):
        metadata = extract_validation_guard_metadata(payload)
        bullet_lines: list[str] = []
        if metadata.reason:
            bullet_lines.append(
                _("Guard message: {message}").format(message=metadata.reason)
            )
        if metadata.llm_message and metadata.llm_message != metadata.reason:
            bullet_lines.append(
                _("LLM message: {message}").format(message=metadata.llm_message)
            )
        duration_seconds = _extract_duration_seconds(payload)
        cost_text = _extract_cost_text(payload)
        started_at = _normalise_timestamp(
            payload.get("started_at") or payload.get("first_observed_at")
        )
        completed_at = _normalise_timestamp(payload.get("completed_at"))
        last_observed = _normalise_timestamp(
            payload.get("last_observed_at") or payload.get("observed_at")
        )
        return ToolCallSummary(
            index=index,
            tool_name=_("LLM validation guard"),
            status=_("blocked invalid response"),
            bullet_lines=tuple(bullet_lines),
            started_at=started_at,
            completed_at=completed_at,
            last_observed_at=last_observed,
            duration=duration_seconds,
            cost=cost_text,
            error_message=extract_error_message(payload.get("error")),
            arguments=None,
            category="validation_guard",
        )

    tool_name = extract_tool_name(payload)
    status = format_tool_status(payload)
    bullet_lines = list(summarize_tool_details(payload))
    duration_seconds = _extract_duration_seconds(payload)
    cost_text = _extract_cost_text(payload)
    error_text = _derive_error_message(payload)
    arguments = _extract_arguments(payload)
    started_at = _normalise_timestamp(
        payload.get("started_at") or payload.get("first_observed_at")
    )
    completed_at = _normalise_timestamp(payload.get("completed_at"))
    last_observed = _normalise_timestamp(
        payload.get("last_observed_at") or payload.get("observed_at")
    )
    return ToolCallSummary(
        index=index,
        tool_name=tool_name,
        status=status,
        bullet_lines=tuple(bullet_lines),
        started_at=started_at,
        completed_at=completed_at,
        last_observed_at=last_observed,
        duration=duration_seconds,
        cost=cost_text,
        error_message=error_text,
        arguments=arguments,
    )


def is_validation_guard_payload(payload: Mapping[str, Any]) -> bool:
    """Return ``True`` if *payload* corresponds to a validation guard entry."""

    if not isinstance(payload, Mapping):
        return False

    def _matches_name(value: Any) -> bool:
        return isinstance(value, str) and value.strip().lower() == "invalid_tool_call"

    if _matches_name(payload.get("tool_name")):
        return True

    tool_section = payload.get("tool")
    if isinstance(tool_section, Mapping) and _matches_name(tool_section.get("name")):
        return True

    if _matches_name(payload.get("name")):
        return True

    error_payload = payload.get("error")
    if isinstance(error_payload, Mapping):
        details = error_payload.get("details")
        if isinstance(details, Mapping):
            error_type = details.get("type")
            if isinstance(error_type, str) and error_type.strip():
                if error_type.strip().lower() == "toolvalidationerror":
                    return True
    return False


def extract_validation_guard_metadata(
    payload: Mapping[str, Any]
) -> ValidationGuardMetadata:
    """Return structured metadata extracted from a validation guard payload."""

    reason = _normalise_optional_string(payload.get("reason"))
    error_payload = payload.get("error")
    details_payload: Mapping[str, Any] | None = None
    llm_message: str | None = None
    code: str | None = None

    if isinstance(error_payload, Mapping):
        if reason is None:
            reason = _normalise_optional_string(error_payload.get("message"))
        code = _normalise_optional_string(error_payload.get("code"))
        details_candidate = error_payload.get("details")
        if isinstance(details_candidate, Mapping):
            details_payload = details_candidate
            llm_message = _normalise_optional_string(
                details_candidate.get("llm_message")
            )
            if llm_message is None:
                llm_message = _normalise_optional_string(
                    details_candidate.get("message")
                )

    return ValidationGuardMetadata(
        reason=reason,
        llm_message=llm_message,
        code=code,
        details=details_payload,
    )


def render_tool_summary_markdown(summary: ToolCallSummary) -> str:
    base = _("Agent: tool call {index}: {tool} — {status}")
    heading = base.format(
        index=summary.index,
        tool=f"**{summary.tool_name}**",
        status=summary.status,
    )
    heading = normalize_for_display(heading)
    lines = ["> 🔧 " + heading]
    for bullet in summary.bullet_lines:
        if bullet:
            lines.append("> • " + normalize_for_display(bullet))
    return "\n".join(lines)


def render_tool_summaries_markdown(
    summaries: Sequence[ToolCallSummary],
) -> str:
    if not summaries:
        return ""
    blocks: list[str] = []
    for summary in summaries:
        block = render_tool_summary_markdown(summary)
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def render_tool_summaries_plain(
    summaries: Sequence[ToolCallSummary],
) -> str:
    if not summaries:
        return ""
    base = _("Agent: tool call {index}: {tool} — {status}")
    blocks: list[str] = []
    for summary in summaries:
        heading = base.format(
            index=summary.index,
            tool=summary.tool_name,
            status=summary.status,
        )
        heading = normalize_for_display(heading)
        lines = [heading]
        for bullet in summary.bullet_lines:
            if bullet:
                lines.append("    • " + normalize_for_display(bullet))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def extract_tool_name(payload: Mapping[str, Any]) -> str:
    for key in ("tool_name", "tool", "name"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return normalize_for_display(text)
    return normalize_for_display(_("Unnamed tool"))


def format_tool_status(payload: Mapping[str, Any]) -> str:
    agent_status = payload.get("agent_status")
    if isinstance(agent_status, str):
        status_text = agent_status.strip()
        if not status_text:
            pass
        else:
            prefix, separator, remainder = status_text.partition(":")
            normalized_prefix = prefix.strip().lower()
            if normalized_prefix == "running":
                return normalize_for_display(_("in progress…"))
            if normalized_prefix == "completed":
                return normalize_for_display(_("completed"))
            if normalized_prefix == "failed":
                return normalize_for_display(_("failed"))
            normalized_full = status_text.lower()
            if normalized_full == "running":
                return normalize_for_display(_("in progress…"))
            if normalized_full == "completed":
                return normalize_for_display(_("completed"))
            if normalized_full == "failed":
                return normalize_for_display(_("failed"))
            return normalize_for_display(shorten_text(status_text))
    ok_value = payload.get("ok")
    if ok_value is True:
        return normalize_for_display(_("completed successfully"))
    if ok_value is False:
        return normalize_for_display(_("failed"))
    return normalize_for_display(_("returned data"))


def extract_error_message(error: Any) -> str:
    if not error:
        return ""
    if isinstance(error, Mapping):
        for key in ("message", "detail", "error"):
            value = error.get(key)
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return shorten_text(normalize_for_display(text))
        code = error.get("code")
        if isinstance(code, str) and code.strip():
            return shorten_text(
                normalize_for_display(
                    _("code {code}").format(code=code.strip())
                )
            )
        try:
            return shorten_text(
                normalize_for_display(
                    json.dumps(error, ensure_ascii=False, default=str)
                )
            )
        except Exception:  # pragma: no cover - defensive
            return shorten_text(normalize_for_display(str(error)))
    if isinstance(error, Sequence) and not isinstance(
        error, (str, bytes, bytearray)
    ):
        items = [normalize_for_display(str(item)) for item in error[:5]]
        if len(error) > 5:
            items.append("…")
        return shorten_text(", ".join(items))
    return shorten_text(normalize_for_display(str(error)))


def summarize_tool_details(payload: Mapping[str, Any]) -> list[str]:
    tool_name = extract_tool_name(payload)
    arguments = payload.get("tool_arguments")
    result = payload.get("result")
    lines, consumed_args, consumed_result = summarize_specific_tool(
        tool_name, arguments, result
    )
    extra_lines, displayed_argument_keys = summarize_generic_arguments(
        arguments, consumed_args
    )
    lines.extend(extra_lines)
    if consumed_result is not None and "rid" in displayed_argument_keys:
        consumed_result.add("rid")
    if payload.get("ok") is False:
        lines.extend(summarize_error_details(payload.get("error")))
        return [line for line in lines if line]
    if consumed_result is not None:
        lines.extend(summarize_generic_result(result, consumed_result))
    return [line for line in lines if line]


def summarize_error_details(error: Any) -> list[str]:
    if not error:
        return []
    if isinstance(error, Mapping):
        lines: list[str] = []
        code_raw = error.get("code")
        code_text: str | None = None
        if isinstance(code_raw, str) and code_raw.strip():
            code_text = normalize_for_display(code_raw.strip())
        message = error.get("message")
        message_text: str | None = None
        if isinstance(message, str) and message.strip():
            message_text = shorten_text(normalize_for_display(message.strip()))
        if code_text and message_text:
            lines.append(
                _("Error {code}: [{code}] {message}").format(
                    code=code_text,
                    message=message_text,
                )
            )
        else:
            if code_text:
                lines.append(
                    _("Error {code}: [{code}]").format(code=code_text)
                )
            if message_text:
                lines.append(
                    _("Error: {message}").format(message=message_text)
                )
        details = error.get("details")
        if details:
            lines.append(
                _("Error details: {details}").format(
                    details=format_value_snippet(details)
                )
            )
        return lines
    return [_("Error: {message}").format(message=format_value_snippet(error))]


def summarize_specific_tool(
    tool_name: str, arguments: Any, result: Any
) -> tuple[list[str], set[str], set[str] | None]:
    lines: list[str] = []
    consumed_args: set[str] = set()
    consumed_result: set[str] | None = set()

    rid = extract_rid(arguments, result)
    if tool_name == "update_requirement_field":
        if rid:
            lines.append(
                _("Requirement: {rid}").format(rid=format_value_snippet(rid))
            )
            consumed_args.add("rid")

        change_field: str | None = None
        previous_display: str | None = None
        current_display: str | None = None
        if isinstance(result, Mapping):
            change_section = result.get("field_change")
            if isinstance(change_section, Mapping):
                raw_change_field = change_section.get("field")
                if isinstance(raw_change_field, str):
                    text = raw_change_field.strip()
                    if text:
                        change_field = normalize_for_display(text)
                if "previous" in change_section:
                    previous_display = format_value_snippet(
                        change_section.get("previous")
                    )
                if "current" in change_section:
                    current_display = format_value_snippet(
                        change_section.get("current")
                    )

        if isinstance(arguments, Mapping):
            field = arguments.get("field")
            if field is not None:
                lines.append(
                    _("Field: {field}").format(
                        field=format_value_snippet(field)
                    )
                )
                consumed_args.add("field")
            elif change_field is not None:
                lines.append(
                    _("Field: {field}").format(
                        field=format_value_snippet(change_field)
                    )
                )
            if "value" in arguments:
                consumed_args.add("value")
                if current_display is None:
                    current_display = format_value_snippet(arguments.get("value"))
        elif change_field is not None:
            lines.append(
                _("Field: {field}").format(
                    field=format_value_snippet(change_field)
                )
            )

        if previous_display is not None:
            lines.append(
                _("Previous value: {value}").format(value=previous_display)
            )
        if current_display is not None:
            lines.append(
                _("New value: {value}").format(value=current_display)
            )

        if isinstance(result, Mapping):
            revision = result.get("revision")
            if revision is not None:
                lines.append(
                    _("Revision: {revision}").format(
                        revision=format_value_snippet(revision)
                    )
                )
        return lines, consumed_args, None

    if tool_name == "set_requirement_labels":
        if rid:
            lines.append(
                _("Requirement: {rid}").format(rid=format_value_snippet(rid))
            )
            consumed_args.add("rid")
        labels_value = None
        if isinstance(arguments, Mapping):
            labels_value = arguments.get("labels")
            consumed_args.add("labels")
        if labels_value is None:
            lines.append(_("Labels cleared"))
        else:
            lines.append(
                _("Labels: {labels}").format(
                    labels=format_value_snippet(labels_value)
                )
            )
        return lines, consumed_args, None

    if tool_name == "set_requirement_attachments":
        if rid:
            lines.append(
                _("Requirement: {rid}").format(rid=format_value_snippet(rid))
            )
            consumed_args.add("rid")
        attachments = None
        if isinstance(arguments, Mapping):
            attachments = arguments.get("attachments")
            consumed_args.add("attachments")
        count = (
            len(attachments)
            if isinstance(attachments, Sequence)
            and not isinstance(attachments, (str, bytes, bytearray))
            else 0
        )
        lines.append(
            _("Attachments provided: {count}").format(
                count=normalize_for_display(str(count))
            )
        )
        if isinstance(result, Mapping):
            new_attachments = result.get("attachments")
            if isinstance(new_attachments, Sequence) and not isinstance(
                new_attachments, (str, bytes, bytearray)
            ):
                lines.append(
                    _("Current attachment count: {count}").format(
                        count=normalize_for_display(str(len(new_attachments)))
                    )
                )
        return lines, consumed_args, None

    if tool_name == "set_requirement_links":
        if rid:
            lines.append(
                _("Requirement: {rid}").format(rid=format_value_snippet(rid))
            )
            consumed_args.add("rid")
        links_value = None
        if isinstance(arguments, Mapping):
            links_value = arguments.get("links")
            consumed_args.add("links")
        if isinstance(links_value, Sequence) and not isinstance(
            links_value, (str, bytes, bytearray)
        ):
            lines.append(
                _("Outgoing links provided: {count}").format(
                    count=normalize_for_display(str(len(links_value)))
                )
            )
        elif links_value is None:
            lines.append(_("Outgoing links cleared"))
        if isinstance(result, Mapping):
            new_links = result.get("links")
            if isinstance(new_links, Sequence) and not isinstance(
                new_links, (str, bytes, bytearray)
            ):
                lines.append(
                    _("Current outgoing links: {count}").format(
                        count=normalize_for_display(str(len(new_links)))
                    )
                )
        return lines, consumed_args, None

    if tool_name == "delete_requirement":
        if rid:
            lines.append(
                _("Deleted requirement: {rid}").format(
                    rid=format_value_snippet(rid)
                )
            )
        return lines, consumed_args, None

    if tool_name == "create_requirement":
        if isinstance(arguments, Mapping):
            prefix = arguments.get("prefix")
            if prefix is not None:
                lines.append(
                    _("Document: {prefix}").format(
                        prefix=format_value_snippet(prefix)
                    )
                )
                consumed_args.add("prefix")
        if isinstance(result, Mapping):
            rid_result = result.get("rid")
            if rid_result:
                lines.append(
                    _("Created requirement: {rid}").format(
                        rid=format_value_snippet(rid_result)
                    )
                )
        return lines, consumed_args, None

    if tool_name == "search_requirements":
        if isinstance(arguments, Mapping):
            query = arguments.get("query")
            if query:
                lines.append(
                    _("Query: {query}").format(
                        query=format_value_snippet(query)
                    )
                )
                consumed_args.add("query")
            filters = arguments.get("filters")
            if filters:
                lines.append(
                    _("Filters: {filters}").format(
                        filters=format_value_snippet(filters)
                    )
                )
                consumed_args.add("filters")
        if isinstance(result, Mapping):
            total = result.get("total")
            if total is not None:
                lines.append(
                    _("Matching requirements: {count}").format(
                        count=format_value_snippet(total)
                    )
                )
        return lines, consumed_args, None

    if tool_name == "link_requirements":
        if isinstance(arguments, Mapping):
            source = arguments.get("source")
            if source:
                lines.append(
                    _("Source: {rid}").format(
                        rid=format_value_snippet(source)
                    )
                )
                consumed_args.add("source")
            targets = arguments.get("targets")
            if targets:
                lines.append(
                    _("Targets: {targets}").format(
                        targets=format_value_snippet(targets)
                    )
                )
                consumed_args.add("targets")
        return lines, consumed_args, None

    if tool_name == "set_requirement_status":
        if rid:
            lines.append(
                _("Requirement: {rid}").format(rid=format_value_snippet(rid))
            )
            consumed_args.add("rid")
        if isinstance(arguments, Mapping):
            status = arguments.get("status")
            if status:
                lines.append(
                    _("Status: {status}").format(
                        status=format_value_snippet(status)
                    )
                )
                consumed_args.add("status")
        return lines, consumed_args, None

    if tool_name == "set_requirement_priority":
        if rid:
            lines.append(
                _("Requirement: {rid}").format(rid=format_value_snippet(rid))
            )
            consumed_args.add("rid")
        if isinstance(arguments, Mapping):
            priority = arguments.get("priority")
            if priority is not None:
                lines.append(
                    _("Priority: {priority}").format(
                        priority=format_value_snippet(priority)
                    )
                )
                consumed_args.add("priority")
        return lines, consumed_args, None

    if tool_name == "set_requirement_owner":
        if rid:
            lines.append(
                _("Requirement: {rid}").format(rid=format_value_snippet(rid))
            )
            consumed_args.add("rid")
        if isinstance(arguments, Mapping):
            owner = arguments.get("owner")
            if owner:
                lines.append(
                    _("Owner: {owner}").format(
                        owner=format_value_snippet(owner)
                    )
                )
                consumed_args.add("owner")
        return lines, consumed_args, None

    if tool_name == "update_requirement_tags":
        if rid:
            lines.append(
                _("Requirement: {rid}").format(rid=format_value_snippet(rid))
            )
            consumed_args.add("rid")
        if isinstance(arguments, Mapping):
            tags = arguments.get("tags")
            if tags:
                lines.append(
                    _("Tags: {tags}").format(
                        tags=format_value_snippet(tags)
                    )
                )
                consumed_args.add("tags")
        return lines, consumed_args, None

    return lines, consumed_args, consumed_result


def summarize_generic_arguments(
    arguments: Any, consumed: set[str]
) -> tuple[list[str], set[str]]:
    if not isinstance(arguments, Mapping):
        if arguments is None:
            return [], set()
        return (
            [
                _("Arguments: {value}").format(
                    value=format_value_snippet(arguments)
                )
            ],
            set(),
        )
    skip = set(consumed)
    skip.add("directory")
    lines: list[str] = []
    displayed: set[str] = set()
    for key in arguments:
        if len(lines) >= 5:
            break
        if key in skip:
            continue
        value = arguments.get(key)
        if isinstance(key, str) and key.lower() == "rid":
            lines.append(
                _("Requirement: {rid}").format(
                    rid=format_value_snippet(value)
                )
            )
            displayed.add("rid")
            skip.add(key)
            continue
        lines.append(
            _("{label}: {value}").format(
                label=prettify_key(key), value=format_value_snippet(value)
            )
        )
        if isinstance(key, str):
            displayed.add(key)
    return lines, displayed


def summarize_generic_result(
    result: Any, consumed: set[str]
) -> list[str]:
    if result is None:
        return []
    if not isinstance(result, Mapping):
        return [
            _("Result: {value}").format(value=format_value_snippet(result))
        ]
    skip = set(consumed)
    lines: list[str] = []
    if "rid" in result and "rid" not in skip:
        lines.append(
            _("Requirement: {rid}").format(
                rid=format_value_snippet(result.get("rid"))
            )
        )
        skip.add("rid")
    if "title" in result and "title" not in skip:
        lines.append(
            _("Title: {title}").format(
                title=format_value_snippet(result.get("title"))
            )
        )
        skip.add("title")
    if "total" in result and "total" not in skip:
        lines.append(
            _("Total items: {total}").format(
                total=format_value_snippet(result.get("total"))
            )
        )
        skip.add("total")
    if "items" in result and "items" not in skip:
        items = result.get("items")
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
            lines.append(
                _("Returned items: {count}").format(
                    count=format_value_snippet(len(items))
                )
            )
        skip.add("items")
    for key in result:
        if len(lines) >= 5:
            break
        if key in skip or key in {"links", "labels", "attachments"}:
            continue
        value = result.get(key)
        lines.append(
            _("{label}: {value}").format(
                label=prettify_key(key), value=format_value_snippet(value)
            )
        )
    return lines


def prettify_key(key: Any) -> str:
    text = normalize_for_display(str(key))
    return text.replace("_", " ").capitalize()


def extract_rid(arguments: Any, result: Any) -> str | None:
    for source in (arguments, result):
        if isinstance(source, Mapping):
            rid = source.get("rid")
            if isinstance(rid, str):
                text = rid.strip()
                if text:
                    return normalize_for_display(text)
    return None


def format_value_snippet(value: Any) -> str:
    if value is None:
        return _("(none)")
    if isinstance(value, str):
        text = normalize_for_display(value.strip())
        if not text:
            return _("(empty)")
        text = shorten_text(text)
        if "\n" not in text and "`" not in text:
            return f"`{text}`"
        return text
    if isinstance(value, (int, float)):
        return normalize_for_display(str(value))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items: list[str] = []
        for item in value:
            items.append(shorten_text(normalize_for_display(str(item)), limit=40))
            if len(items) >= 5:
                break
        if len(value) > 5:
            items.append("")
        joined = ", ".join(item for item in items if item)
        if not joined:
            return _("(empty)")
        if "\n" not in joined and "`" not in joined:
            return f"`{joined}`"
        return joined
    if isinstance(value, Mapping):
        keys: list[str] = []
        for key in value:
            keys.append(normalize_for_display(str(key)))
            if len(keys) >= 5:
                break
        if len(value) > 5:
            keys.append("…")
        keys_text = ", ".join(keys) if keys else _("(none)")
        return _("keys: {keys}").format(keys=keys_text)
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # pragma: no cover - defensive
        text = normalize_for_display(str(value))
    text = shorten_text(text)
    if "\n" not in text and "`" not in text:
        return f"`{text}`"
    return text


def shorten_text(text: str, *, limit: int = 120) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


__all__ = [
    "ToolCallSummary",
    "ValidationGuardMetadata",
    "summarize_tool_results",
    "summarize_tool_payload",
    "is_validation_guard_payload",
    "extract_validation_guard_metadata",
    "render_tool_summary_markdown",
    "render_tool_summaries_markdown",
    "render_tool_summaries_plain",
    "extract_error_message",
    "summarize_error_details",
    "format_value_snippet",
    "shorten_text",
]
