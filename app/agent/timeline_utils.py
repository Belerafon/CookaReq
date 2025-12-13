"""Utilities for canonical agent timeline handling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Protocol, Sequence


class _SupportsTimelineEntry(Protocol):
    kind: str
    sequence: int | None
    occurred_at: str | None
    step_index: int | None
    call_id: str | None
    status: str | None


@dataclass(frozen=True)
class TimelineIntegrity:
    status: Literal["valid", "missing", "damaged"]
    checksum: str | None
    issues: tuple[str, ...] = ()


def assess_timeline_integrity(
    timeline: Sequence[_SupportsTimelineEntry] | Iterable[_SupportsTimelineEntry],
    *,
    declared_checksum: str | None = None,
) -> TimelineIntegrity:
    """Classify timeline consistency without mutating it."""

    entries = tuple(timeline)
    if not entries:
        return TimelineIntegrity(status="missing", checksum=None, issues=())

    issues: list[str] = []
    sequences: list[int] = []
    call_ids: set[str] = set()

    for entry in entries:
        if entry.sequence is None:
            issues.append("missing_sequence")
        else:
            sequences.append(entry.sequence)

        if entry.kind == "tool_call":
            if not entry.call_id:
                issues.append("missing_call_id")
            elif entry.call_id in call_ids:
                issues.append("duplicate_call_id")
            else:
                call_ids.add(entry.call_id)

    if sequences:
        unique_sequences = set(sequences)
        if len(unique_sequences) != len(sequences):
            issues.append("duplicate_sequence")

        sorted_sequences = sorted(unique_sequences)
        expected = sorted_sequences[0]
        for value in sorted_sequences:
            if value != expected:
                issues.append("non_contiguous_sequence")
                break
            expected += 1

    try:
        checksum = timeline_checksum(entries)
    except Exception:
        checksum = None
        issues.append("checksum_error")

    if declared_checksum and checksum and declared_checksum != checksum:
        issues.append("checksum_mismatch")

    status: Literal["valid", "missing", "damaged"] = "valid" if not issues else "damaged"
    return TimelineIntegrity(status=status, checksum=checksum, issues=tuple(issues))


def timeline_checksum(
    timeline: Sequence[_SupportsTimelineEntry]
    | Iterable[_SupportsTimelineEntry],
) -> str:
    """Return a deterministic checksum for a canonical agent timeline.

    The checksum captures the ordered list of timeline entries using stable fields
    (`kind`, `sequence`, `occurred_at`, `step_index`, `call_id`, `status`). The
    intent is to let caches depend on the already canonized timeline instead of
    mixing in diagnostic sources like raw event logs or tool snapshots.
    """

    digest = hashlib.sha256()
    for entry in timeline:
        normalized_entry = {
            "kind": entry.kind,
            "sequence": entry.sequence,
            "occurred_at": entry.occurred_at,
            "step_index": entry.step_index,
            "call_id": entry.call_id,
            "status": entry.status,
        }
        digest.update(_stable_dump(normalized_entry))
    return digest.hexdigest()


def _stable_dump(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
