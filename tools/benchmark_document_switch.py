#!/usr/bin/env python3
"""Benchmark document switching latency for large requirement lists."""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import wx

from app.core.model import Priority, RequirementType, Status, Verification
from app.services.requirements import RequirementsService
from app.ui.controllers.documents import DocumentsController
from app.ui.list_panel import ListPanel
from app.ui.requirement_model import RequirementModel


@dataclass(slots=True)
class BenchmarkResult:
    """Aggregate timings for one benchmark run."""

    load_durations_ms: list[float]
    render_durations_ms: list[float]
    sort_durations_ms: list[float]


def _long_markdown_block(base: str, *, repeat: int) -> str:
    blocks: list[str] = []
    for index in range(1, repeat + 1):
        blocks.append(
            "\n".join(
                [
                    f"### {base} section {index}",
                    "- bullet one",
                    "- bullet two",
                    "- bullet three",
                    "",
                    "| Col A | Col B | Col C |",
                    "| --- | --- | --- |",
                    "| Value 1 | Value 2 | Value 3 |",
                    "",
                    "Текст для проверки производительности на менее быстрых машинах.",
                ]
            )
        )
    return "\n\n".join(blocks)


def _build_dataset(root: Path, *, per_doc: int, statement_size: int) -> None:
    service = RequirementsService(root)
    service.create_document(prefix="SYS", title="System")
    service.create_document(prefix="HLR", title="High-Level")

    statement_suffix = "A" * statement_size
    long_notes = _long_markdown_block("Notes", repeat=4)
    long_rationale = _long_markdown_block("Rationale", repeat=4)
    long_conditions = _long_markdown_block("Conditions", repeat=3)
    long_assumptions = _long_markdown_block("Assumptions", repeat=3)

    for prefix in ("SYS", "HLR"):
        for req_id in range(1, per_doc + 1):
            links: list[dict[str, object]] = []
            if req_id > 1:
                links.append({"rid": f"{prefix}{req_id - 1}", "revision": 1})
            if req_id > 10:
                links.append({"rid": f"{prefix}{req_id - 10}", "revision": 1})
            service.create_requirement(
                prefix,
                {
                    "id": req_id,
                    "title": f"{prefix} requirement {per_doc - req_id:04d}",
                    "statement": (
                        "# Heading\n"
                        "Text with **markdown** and [link](https://example.com).\n\n"
                        "- item 1\n- item 2\n\n"
                        f"{statement_suffix}\n\n"
                        "```\ncode block\n```"
                    ),
                    "type": RequirementType.REQUIREMENT.value,
                    "status": Status.DRAFT.value,
                    "priority": Priority.MEDIUM.value,
                    "verification": Verification.ANALYSIS.value,
                    "owner": f"owner-{req_id % 7}",
                    "source": "benchmark",
                    "labels": [],
                    "acceptance": (
                        "Система должна отвечать за <= 250 мс при нагрузке 500 rps. "
                        f"Сценарий #{req_id}."
                    ),
                    "conditions": long_conditions,
                    "rationale": long_rationale,
                    "assumptions": long_assumptions,
                    "notes": long_notes,
                    "context_docs": ["context/overview.md", "context/glossary.md"],
                    "links": links,
                },
            )


def _run_benchmark(
    root: Path,
    *,
    iterations: int,
    sort_column: str,
    resort_each_switch: bool,
) -> BenchmarkResult:
    model = RequirementModel()
    service = RequirementsService(root)
    controller = DocumentsController(service, model)
    controller.load_documents()

    app = wx.App(False)
    frame = wx.Frame(None)
    panel = ListPanel(frame, model=model)
    panel.set_columns(
        ["id", "statement", "status", "owner", "rationale", "notes", "links", "derived_count"]
    )

    if sort_column not in panel._field_order:
        available = ", ".join(panel._field_order)
        raise ValueError(f"Unknown sort column '{sort_column}'. Available: {available}")
    sort_col_index = panel._field_order.index(sort_column)

    # Prime sort once so following document switches keep sort in model without extra redraw.
    panel.sort(sort_col_index, True)

    load_durations_ms: list[float] = []
    render_durations_ms: list[float] = []
    sort_durations_ms: list[float] = []

    order = ["SYS", "HLR"]
    sort_ascending = True
    for index in range(iterations):
        prefix = order[index % 2]

        t0 = time.perf_counter()
        derived_map = controller.load_items(prefix)
        t1 = time.perf_counter()
        panel.set_requirements(model.get_all(), derived_map)
        t2 = time.perf_counter()

        sort_ms = 0.0
        if resort_each_switch:
            panel.sort(sort_col_index, sort_ascending)
            t3 = time.perf_counter()
            sort_ms = (t3 - t2) * 1000
            sort_ascending = not sort_ascending

        load_durations_ms.append((t1 - t0) * 1000)
        render_durations_ms.append((t2 - t1) * 1000)
        sort_durations_ms.append(sort_ms)

    frame.Destroy()
    app.Destroy()
    return BenchmarkResult(
        load_durations_ms=load_durations_ms,
        render_durations_ms=render_durations_ms,
        sort_durations_ms=sort_durations_ms,
    )


def _profile_operation(root: Path, *, sort_column: str) -> tuple[str, str]:
    model = RequirementModel()
    service = RequirementsService(root)
    controller = DocumentsController(service, model)
    controller.load_documents()

    app = wx.App(False)
    frame = wx.Frame(None)
    panel = ListPanel(frame, model=model)
    panel.set_columns(
        ["id", "statement", "status", "owner", "rationale", "notes", "links", "derived_count"]
    )
    sort_col_index = panel._field_order.index(sort_column)

    derived_map = controller.load_items("SYS")

    # Scenario A: normal switch with sort already active in model.
    panel.sort(sort_col_index, True)
    render_profile = cProfile.Profile()
    render_profile.enable()
    panel.set_requirements(model.get_all(), derived_map)
    render_profile.disable()

    # Scenario B: explicit re-sort call (extra repaint) after refresh.
    sort_profile = cProfile.Profile()
    sort_profile.enable()
    panel.sort(sort_col_index, False)
    sort_profile.disable()

    render_stream = io.StringIO()
    sort_stream = io.StringIO()
    pstats.Stats(render_profile, stream=render_stream).sort_stats("cumtime").print_stats(20)
    pstats.Stats(sort_profile, stream=sort_stream).sort_stats("cumtime").print_stats(20)

    frame.Destroy()
    app.Destroy()
    return render_stream.getvalue(), sort_stream.getvalue()


def _fmt(values: list[float]) -> str:
    if not values:
        return "mean=0.00 ms, max=0.00 ms"
    if len(values) < 2:
        return f"mean={statistics.mean(values):.2f} ms, max={max(values):.2f} ms"
    return (
        f"mean={statistics.mean(values):.2f} ms, "
        f"p95={statistics.quantiles(values, n=20)[-1]:.2f} ms, "
        f"max={max(values):.2f} ms"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-doc", type=int, default=150)
    parser.add_argument("--statement-size", type=int, default=1200)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument(
        "--sort-column",
        type=str,
        default="title",
        help="Column used for sorting (default: title).",
    )
    parser.add_argument(
        "--resort-each-switch",
        action="store_true",
        help=(
            "Force explicit sort call after each switch (double repaint scenario). "
            "By default benchmark measures normal flow with one repaint per switch."
        ),
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="cookareq-switch-bench-") as tmp:
        root = Path(tmp)
        _build_dataset(root, per_doc=args.per_doc, statement_size=args.statement_size)
        result = _run_benchmark(
            root,
            iterations=args.iterations,
            sort_column=args.sort_column,
            resort_each_switch=args.resort_each_switch,
        )

        print("Dataset:")
        print(f"  docs=2, requirements/doc={args.per_doc}, statement_size={args.statement_size}")
        print("Switch benchmark:")
        print(f"  load_items: {_fmt(result.load_durations_ms)}")
        print(f"  list_render: {_fmt(result.render_durations_ms)}")
        if args.resort_each_switch:
            print(f"  explicit sort({args.sort_column}): {_fmt(result.sort_durations_ms)}")
            print(
                "  combined(load+render+sort): "
                + _fmt(
                    [
                        load + render + sort
                        for load, render, sort in zip(
                            result.load_durations_ms,
                            result.render_durations_ms,
                            result.sort_durations_ms,
                            strict=True,
                        )
                    ]
                )
            )
        else:
            print(
                "  combined(load+render): "
                + _fmt(
                    [
                        load + render
                        for load, render in zip(
                            result.load_durations_ms,
                            result.render_durations_ms,
                            strict=True,
                        )
                    ]
                )
            )

        render_profile, sort_profile = _profile_operation(root, sort_column=args.sort_column)
        print("\nTop profile: switch with active sort (single repaint)")
        print(render_profile)
        print("Top profile: explicit sort call after switch (extra repaint)")
        print(sort_profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
