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
from pathlib import Path

import wx

from app.core.model import Priority, RequirementType, Status, Verification
from app.services.requirements import RequirementsService
from app.ui.controllers.documents import DocumentsController
from app.ui.list_panel import ListPanel
from app.ui.requirement_model import RequirementModel


def _build_dataset(root: Path, *, per_doc: int, statement_size: int) -> None:
    service = RequirementsService(root)
    service.create_document(prefix="SYS", title="System")
    service.create_document(prefix="HLR", title="High-Level")
    statement = (
        "# Heading\n"
        "Text with **markdown** and [link](https://example.com).\n\n"
        "- item 1\n- item 2\n\n"
        + ("A" * statement_size)
    )
    for prefix in ("SYS", "HLR"):
        for req_id in range(1, per_doc + 1):
            service.create_requirement(
                prefix,
                {
                    "id": req_id,
                    "title": f"{prefix} requirement {req_id}",
                    "statement": statement,
                    "type": RequirementType.REQUIREMENT.value,
                    "status": Status.DRAFT.value,
                    "priority": Priority.MEDIUM.value,
                    "verification": Verification.ANALYSIS.value,
                    "owner": "",
                    "source": "benchmark",
                    "labels": [],
                },
            )


def _run_benchmark(root: Path, *, iterations: int) -> tuple[list[float], list[float]]:
    model = RequirementModel()
    service = RequirementsService(root)
    controller = DocumentsController(service, model)
    controller.load_documents()

    app = wx.App(False)
    frame = wx.Frame(None)
    panel = ListPanel(frame, model=model)
    panel.set_columns(["id", "statement", "status", "labels", "derived_count"])

    load_durations_ms: list[float] = []
    render_durations_ms: list[float] = []

    order = ["SYS", "HLR"]
    for index in range(iterations):
        prefix = order[index % 2]

        t0 = time.perf_counter()
        derived_map = controller.load_items(prefix)
        t1 = time.perf_counter()
        panel.set_requirements(model.get_all(), derived_map)
        t2 = time.perf_counter()

        load_durations_ms.append((t1 - t0) * 1000)
        render_durations_ms.append((t2 - t1) * 1000)

    frame.Destroy()
    app.Destroy()
    return load_durations_ms, render_durations_ms


def _profile_render(root: Path) -> str:
    model = RequirementModel()
    service = RequirementsService(root)
    controller = DocumentsController(service, model)
    controller.load_documents()

    app = wx.App(False)
    frame = wx.Frame(None)
    panel = ListPanel(frame, model=model)
    panel.set_columns(["id", "statement", "status", "labels", "derived_count"])

    derived_map = controller.load_items("SYS")
    profile = cProfile.Profile()
    profile.enable()
    panel.set_requirements(model.get_all(), derived_map)
    profile.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).sort_stats("cumtime")
    stats.print_stats(20)

    frame.Destroy()
    app.Destroy()
    return stream.getvalue()


def _fmt(values: list[float]) -> str:
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
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="cookareq-switch-bench-") as tmp:
        root = Path(tmp)
        _build_dataset(root, per_doc=args.per_doc, statement_size=args.statement_size)
        load_ms, render_ms = _run_benchmark(root, iterations=args.iterations)

        print("Dataset:")
        print(f"  docs=2, requirements/doc={args.per_doc}, statement_size={args.statement_size}")
        print("Switch benchmark:")
        print(f"  load_items: {_fmt(load_ms)}")
        print(f"  list_render: {_fmt(render_ms)}")
        print(
            "  combined: "
            + _fmt([load + render for load, render in zip(load_ms, render_ms, strict=True)])
        )

        print("\nTop render profile (single switch):")
        print(_profile_render(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
