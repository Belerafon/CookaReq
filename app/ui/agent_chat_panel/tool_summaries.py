"""Formatting helpers for MCP tool call summaries."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any

import json

from ...agent.run_contract import ToolError, ToolResultSnapshot
from ...i18n import _
from ...llm.tokenizer import TokenCountResult, count_text_tokens
from ..locale import field_label
from ..text import normalize_for_display
from .history_utils import history_json_safe
from .time_formatting import format_entry_timestamp


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


def summarize_tool_results(
    tool_results: Sequence[Any] | None,
) -> tuple[ToolCallSummary, ...]:
    """Generate summaries for deterministic tool snapshots."""

    if not tool_results:
        return ()

    snapshots: list[ToolResultSnapshot] = []
    for value in tool_results:
        snapshot = _snapshot_from_value(value)
        if snapshot is not None:
            snapshots.append(snapshot)

    if not snapshots:
        return ()

    ordered = sorted(
        enumerate(snapshots),
        key=lambda pair: (
            0 if pair[1].sequence is not None else 1,
            pair[1].sequence if pair[1].sequence is not None else pair[0],
        ),
    )
    summaries = [
        _summarize_snapshot(index, snapshot)
        for index, (_, snapshot) in enumerate(ordered, start=1)
    ]
    return tuple(summaries)


def _snapshot_from_value(value: Any) -> ToolResultSnapshot | None:
    if isinstance(value, ToolResultSnapshot):
        return value
    if isinstance(value, Mapping):
        try:
            return ToolResultSnapshot.from_dict(value)
        except Exception:
            return None
    return None


def _summarize_snapshot(
    index: int, snapshot: ToolResultSnapshot
) -> ToolCallSummary:
    arguments = _sanitize_arguments(snapshot.arguments)
    raw_payload_safe = history_json_safe(snapshot.to_dict())
    raw_payload: Any | None
    if isinstance(raw_payload_safe, Mapping):
        raw_payload = dict(raw_payload_safe)
    else:
        raw_payload = raw_payload_safe
    bullet_lines = summarize_tool_details(snapshot, arguments)

    event_started_at: str | None = None
    event_completed_at: str | None = None
    if snapshot.events:
        ordered_events = sorted(
            (event for event in snapshot.events if event.occurred_at),
            key=lambda item: item.occurred_at,
        )
        if ordered_events:
            event_started_at = ordered_events[0].occurred_at
            event_completed_at = ordered_events[-1].occurred_at

    started_at = snapshot.started_at or event_started_at
    completed_at = snapshot.completed_at or event_completed_at
    last_observed_at = snapshot.last_observed_at or event_completed_at or event_started_at
    return ToolCallSummary(
        index=index,
        tool_name=_normalise_tool_name(snapshot.tool_name),
        status=_format_tool_status(snapshot.status),
        bullet_lines=tuple(bullet_lines),
        started_at=_normalise_timestamp(started_at),
        completed_at=_normalise_timestamp(completed_at),
        last_observed_at=_normalise_timestamp(last_observed_at),
        raw_payload=raw_payload,
        duration=snapshot.metrics.duration_seconds,
        cost=_format_cost_text(snapshot.metrics.cost),
        error_message=_format_error_message(snapshot.error),
        arguments=arguments,
    )


def _normalise_tool_name(name: str) -> str:
    text = normalize_for_display(name or "").strip()
    if text:
        return text
    return normalize_for_display(_("Unnamed tool"))


def _format_tool_status(status: str) -> str:
    mapping = {
        "pending": _("pending"),
        "running": _("in progress…"),
        "succeeded": _("completed"),
        "failed": _("failed"),
    }
    label = mapping.get(status, _("returned data"))
    return normalize_for_display(label)


def _normalise_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    formatted = format_entry_timestamp(text)
    if formatted:
        return normalize_for_display(formatted)
    return normalize_for_display(text)


def _format_cost_text(cost: Mapping[str, Any] | None) -> str | None:
    if not isinstance(cost, Mapping):
        return None
    for key in ("display", "formatted", "text", "label"):
        value = cost.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_for_display(value)
    amount = cost.get("amount")
    currency = cost.get("currency")
    if isinstance(amount, (int, float)):
        if isinstance(currency, str) and currency.strip():
            return normalize_for_display(f"{amount} {currency}")
        return normalize_for_display(str(amount))
    return None


def _format_error_message(error: ToolError | None) -> str | None:
    if error is None:
        return None
    message = normalize_for_display(error.message or "").strip()
    if not message and error.code:
        message = normalize_for_display(str(error.code))
    if not message:
        return None
    return shorten_text(message)


def _sanitize_arguments(arguments: Any) -> Any | None:
    if arguments is None:
        return None
    safe = history_json_safe(arguments)
    if isinstance(safe, Mapping):
        return dict(safe)
    return safe


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


def summarize_tool_details(
    snapshot: ToolResultSnapshot, arguments: Any
) -> list[str]:
    result = snapshot.result
    lines, consumed_args, consumed_result = summarize_specific_tool(
        snapshot.tool_name, arguments, result
    )
    extra_lines, displayed_argument_keys = summarize_generic_arguments(
        arguments, consumed_args
    )
    lines.extend(extra_lines)
    if consumed_result is not None and "rid" in displayed_argument_keys:
        consumed_result.add("rid")
    if snapshot.error is not None:
        lines.extend(_summarize_tool_error(snapshot.error))
        return [line for line in lines if line]
    if consumed_result is not None:
        lines.extend(summarize_generic_result(result, consumed_result))
    return [line for line in lines if line]


def _summarize_tool_error(error: ToolError) -> list[str]:
    lines: list[str] = []
    message = normalize_for_display(error.message or "").strip()
    code_text = normalize_for_display(str(error.code)).strip() if error.code else ""

    # Show a compact tag for coded errors to match timeline/tool summary expectations
    # and keep the code visible even when the message is empty.
    if code_text:
        if message:
            lines.append(_("[{code}] {message}").format(code=code_text, message=message))
        else:
            lines.append(_("[{code}]").format(code=code_text))

    if message:
        lines.append(_("Error: {message}").format(message=message))
    if error.details:
        lines.append(
            _("Error details: {details}").format(
                details=format_value_snippet(error.details)
            )
        )
    return lines


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

    if tool_name == "read_user_document":
        if isinstance(result, Mapping):
            encoding = result.get("encoding")
            if encoding:
                lines.append(
                    _("Encoding: {encoding}").format(
                        encoding=format_value_snippet(encoding)
                    )
                )
                consumed_result.add("encoding")
            source_raw = result.get("encoding_source")
            if isinstance(source_raw, str):
                source = source_raw.strip().lower()
                if source == "fallback":
                    lines.append(
                        _("Encoding detection fell back to {encoding}.").format(
                            encoding=format_value_snippet(encoding)
                        )
                    )
                elif source == "empty":
                    lines.append(_("File is empty; default encoding applied."))
            consumed_result.update({"encoding_source", "encoding_confidence"})
            continuation_hint = result.get("continuation_hint")
            hint_text = _summarize_read_user_document_continuation(continuation_hint)
            if hint_text:
                lines.append(hint_text)
                consumed_result.add("continuation_hint")
        if isinstance(result, Mapping) and "content" in result:
            preview = _summarize_document_content_preview(result.get("content"))
            lines.append(
                _("Content preview: {preview}").format(
                    preview=_wrap_preview_for_display(preview)
                )
            )
            consumed_result.add("content")
        return lines, consumed_args, consumed_result

    if tool_name == "create_user_document":
        if isinstance(arguments, Mapping) and "content" in arguments:
            preview = _summarize_document_content_preview(arguments.get("content"))
            lines.append(
                _("Content preview: {preview}").format(
                    preview=_wrap_preview_for_display(preview)
                )
            )
            consumed_args.add("content")
        return lines, consumed_args, consumed_result

    return lines, consumed_args, consumed_result


def _summarize_read_user_document_continuation(hint: Any) -> str | None:
    if not isinstance(hint, Mapping):
        return None

    start_line = hint.get("next_start_line")
    max_bytes = hint.get("max_chunk_bytes")
    remaining = hint.get("bytes_remaining")
    truncated_mid_line = bool(hint.get("truncated_mid_line"))
    exceeded_limit = bool(hint.get("line_exceeded_chunk_limit"))

    parts: list[str] = []
    if isinstance(start_line, int) and isinstance(max_bytes, int):
        parts.append(
            _(
                "To continue reading, call `read_user_document` with `start_line={start}` "
                "and `max_bytes≤{limit}`."
            ).format(
                start=format_value_snippet(start_line),
                limit=format_value_snippet(max_bytes),
            )
        )
    elif isinstance(start_line, int):
        parts.append(
            _(
                "To continue reading, call `read_user_document` with `start_line={start}`."
            ).format(start=format_value_snippet(start_line))
        )
    elif isinstance(max_bytes, int):
        parts.append(
            _(
                "Request the next chunk with `max_bytes≤{limit}` using `read_user_document`."
            ).format(limit=format_value_snippet(max_bytes))
        )

    if exceeded_limit:
        parts.append(
            _(
                "Increase `max_bytes` to capture the remainder of the truncated line."
            )
        )
    elif truncated_mid_line:
        parts.append(
            _(
                "The previous chunk ended mid-line; a higher `max_bytes` may be required."
            )
        )

    if isinstance(remaining, int) and remaining > 0:
        parts.append(
            _("Approximately {remaining} bytes remain.").format(
                remaining=format_value_snippet(remaining)
            )
        )

    if not parts:
        return None

    details = " ".join(parts)
    return _("Hint: {details}").format(details=normalize_for_display(details))


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
    if isinstance(key, str):
        stripped = key.strip()
        if stripped:
            localized = field_label(stripped)
            if localized:
                return normalize_for_display(localized)
    text = normalize_for_display(str(key))
    cleaned = text.replace("_", " ").strip()
    if not cleaned:
        return ""
    # Fallback to localized capitalization when the field is unknown.
    return normalize_for_display(_(cleaned.capitalize()))


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


def _wrap_preview_for_display(preview: str) -> str:
    cleaned = normalize_for_display(preview)
    if not cleaned:
        return "`" + normalize_for_display(_("(empty)")) + "`"
    return f"`{cleaned}`"


def _summarize_document_content_preview(content: Any) -> str:
    if content is None:
        return normalize_for_display(_("(empty)"))
    try:
        text = str(content)
    except Exception:  # pragma: no cover - defensive
        text = ""
    if not text:
        return normalize_for_display(_("(empty)"))

    prefix_segment = text[:20]
    suffix_segment = text[-20:]
    prefix = _prepare_preview_segment(prefix_segment)
    suffix = _prepare_preview_segment(suffix_segment)
    token_result = count_text_tokens(text)
    token_text = _format_token_metric(token_result)
    line_count = len(text.splitlines())
    if line_count == 0 and text:
        line_count = 1
    info = _("lines: {lines}, tokens: {tokens}, characters: {characters}").format(
        lines=line_count,
        tokens=token_text,
        characters=len(text),
    )
    return f"{prefix}…[{normalize_for_display(info)}]…{suffix}"


def _prepare_preview_segment(segment: str) -> str:
    if not segment:
        return ""
    normalized = segment.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\n", "⏎")
    normalized = normalized.replace("\t", "⇥")
    printable = []
    for char in normalized:
        printable.append(char if char.isprintable() else "�")
    return normalize_for_display("".join(printable))


def _format_token_metric(result: TokenCountResult | None) -> str:
    if result is None:
        return "?"
    tokens = result.tokens
    if tokens is None:
        return "?"
    text = normalize_for_display(str(max(tokens, 0)))
    if result.approximate:
        return f"≈{text}"
    return text


__all__ = [
    "ToolCallSummary",
    "summarize_tool_results",
    "summarize_tool_payload",
    "render_tool_summary_markdown",
    "render_tool_summaries_markdown",
    "render_tool_summaries_plain",
    "extract_error_message",
    "summarize_error_details",
    "format_value_snippet",
    "shorten_text",
]
