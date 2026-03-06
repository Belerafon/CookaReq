"""GUI smoke checks for shared artifacts dialog."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.document_store.types import SharedArtifact
from app.ui.shared_artifacts_dialog import SharedArtifactsDialog

pytestmark = pytest.mark.gui


def _make_artifact(*, artifact_id: str, path: str, title: str, include_in_export: bool = True) -> SharedArtifact:
    return SharedArtifact(
        id=artifact_id,
        path=path,
        title=title,
        note="",
        include_in_export=include_in_export,
        tags=["core", "api"] if include_in_export else [],
    )


@pytest.mark.gui_smoke
def test_dialog_shows_file_size_and_missing_indicator(wx_app, tmp_path: Path) -> None:
    wx = pytest.importorskip("wx")

    prefix = "SYS"
    shared_dir = tmp_path / prefix / "shared"
    shared_dir.mkdir(parents=True)
    existing = shared_dir / "spec.txt"
    existing.write_bytes(b"x" * 2048)

    artifacts = [
        _make_artifact(artifact_id="A1", path="shared/spec.txt", title="Spec"),
        _make_artifact(artifact_id="A2", path="shared/missing.txt", title="Missing", include_in_export=False),
    ]

    frame = wx.Frame(None)
    dlg = SharedArtifactsDialog(
        frame,
        prefix=prefix,
        root=tmp_path,
        artifacts=artifacts,
        on_add=lambda *_args, **_kwargs: None,
        on_remove=lambda *_args, **_kwargs: True,
        on_update=lambda *_args, **_kwargs: None,
    )

    assert dlg._list.GetColumnCount() == 5
    assert dlg._list.GetColumn(2).GetText() == "File size"
    assert dlg._list.GetColumn(3).GetText() == "Tags"
    assert dlg._list.GetItemText(0, 2) == "2.0 KB"
    assert dlg._list.GetItemText(0, 3) == "core, api"
    assert dlg._list.GetItemText(1, 2) == "Missing"
    assert dlg._list.GetItemText(1, 3) == ""

    dlg.Destroy()
    frame.Destroy()


@pytest.mark.gui_smoke
def test_dialog_context_menu_disables_open_for_missing_file(monkeypatch, wx_app, tmp_path: Path) -> None:
    wx = pytest.importorskip("wx")

    prefix = "SYS"
    artifacts = [_make_artifact(artifact_id="A2", path="shared/missing.txt", title="Missing")]

    frame = wx.Frame(None)
    dlg = SharedArtifactsDialog(
        frame,
        prefix=prefix,
        root=tmp_path,
        artifacts=artifacts,
        on_add=lambda *_args, **_kwargs: None,
        on_remove=lambda *_args, **_kwargs: True,
        on_update=lambda *_args, **_kwargs: None,
    )

    dlg._list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    captured: dict[str, bool] = {}

    def fake_popup(menu: wx.Menu) -> None:
        open_item = menu.FindItemByPosition(0)
        open_dir_item = menu.FindItemByPosition(1)
        captured["open_enabled"] = open_item.IsEnabled()
        captured["open_dir_enabled"] = open_dir_item.IsEnabled()

    monkeypatch.setattr(dlg._list, "PopupMenu", fake_popup)

    evt = wx.ContextMenuEvent(wx.EVT_CONTEXT_MENU.typeId, dlg._list.GetId())
    dlg._on_context_menu(evt)

    assert captured["open_enabled"] is False
    assert captured["open_dir_enabled"] is False

    dlg.Destroy()
    frame.Destroy()


@pytest.mark.gui_smoke
def test_dialog_context_menu_uses_stateful_export_caption(monkeypatch, wx_app, tmp_path: Path) -> None:
    wx = pytest.importorskip("wx")

    prefix = "SYS"
    artifacts = [
        _make_artifact(artifact_id="A1", path="shared/spec.txt", title="Spec", include_in_export=True),
        _make_artifact(artifact_id="A2", path="shared/spec2.txt", title="Spec2", include_in_export=False),
    ]

    frame = wx.Frame(None)
    dlg = SharedArtifactsDialog(
        frame,
        prefix=prefix,
        root=tmp_path,
        artifacts=artifacts,
        on_add=lambda *_args, **_kwargs: None,
        on_remove=lambda *_args, **_kwargs: True,
        on_update=lambda *_args, **_kwargs: None,
    )

    seen: list[str] = []

    def fake_popup(menu: wx.Menu) -> None:
        toggle_item = menu.FindItemByPosition(3)
        seen.append(toggle_item.GetItemLabelText())

    monkeypatch.setattr(dlg._list, "PopupMenu", fake_popup)

    dlg._list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    evt1 = wx.ContextMenuEvent(wx.EVT_CONTEXT_MENU.typeId, dlg._list.GetId())
    dlg._on_context_menu(evt1)

    dlg._list.SetItemState(0, 0, wx.LIST_STATE_SELECTED)
    dlg._list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    evt2 = wx.ContextMenuEvent(wx.EVT_CONTEXT_MENU.typeId, dlg._list.GetId())
    dlg._on_context_menu(evt2)

    assert seen == ["Remove from export", "Include in export"]

    dlg.Destroy()
    frame.Destroy()
