"""Syntax smoke checks for critical UI modules."""

from __future__ import annotations

import py_compile
from pathlib import Path


def test_trace_matrix_module_compiles() -> None:
    py_compile.compile(str(Path("app/ui/trace_matrix.py")), doraise=True)


def test_main_frame_documents_module_compiles() -> None:
    py_compile.compile(str(Path("app/ui/main_frame/documents.py")), doraise=True)
