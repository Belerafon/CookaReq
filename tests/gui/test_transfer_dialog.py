from __future__ import annotations

import pytest

from app.services.requirements import Document
from app.ui.transfer_dialog import RequirementTransferDialog


def _document(prefix: str, title: str = "") -> Document:
    return Document(prefix=prefix, title=title)


def test_transfer_dialog_initializes_with_real_wx_buttons(wx_app) -> None:
    dialog = RequirementTransferDialog(
        None,
        documents=[_document("REQ", "Requirements"), _document("HW", "Hardware")],
        current_prefix="REQ",
        selection_count=1,
    )
    try:
        assert dialog._target_choice.GetCount() == 2
    finally:
        dialog.Destroy()


def test_resolve_ok_button_falls_back_to_find_window(monkeypatch, wx_app) -> None:
    wx = pytest.importorskip("wx")
    dialog = RequirementTransferDialog(
        None,
        documents=[_document("REQ", "Requirements")],
        current_prefix="REQ",
        selection_count=1,
    )
    try:
        sentinel = object()
        monkeypatch.setattr(dialog, "FindWindowById", lambda _id: sentinel)

        class _SizerWithoutAffirmativeButton:
            pass

        assert dialog._resolve_ok_button(_SizerWithoutAffirmativeButton()) is sentinel
    finally:
        dialog.Destroy()


def test_resolve_ok_button_handles_type_error(monkeypatch, wx_app) -> None:
    dialog = RequirementTransferDialog(
        None,
        documents=[_document("REQ", "Requirements")],
        current_prefix="REQ",
        selection_count=1,
    )
    try:
        sentinel = object()
        monkeypatch.setattr(dialog, "FindWindowById", lambda _id: sentinel)

        class _SizerWithBrokenGetter:
            def GetAffirmativeButton(self):
                raise TypeError("not supported")

        assert dialog._resolve_ok_button(_SizerWithBrokenGetter()) is sentinel
    finally:
        dialog.Destroy()
