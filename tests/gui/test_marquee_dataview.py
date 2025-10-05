"""Regression checks for :mod:`app.ui.widgets.marquee_dataview`."""

from __future__ import annotations

import wx
import wx.dataview as dv

import pytest

from app.ui.widgets.marquee_dataview import MarqueeDataViewListCtrl


pytestmark = [pytest.mark.gui, pytest.mark.gui_smoke]


def _row_rect(control: MarqueeDataViewListCtrl, row: int) -> wx.Rect:
    item = control.RowToItem(row)
    result = control.GetItemRect(item)
    if isinstance(result, tuple):
        success, rect = result
        assert success
    else:
        rect = result
    assert isinstance(rect, wx.Rect)
    return wx.Rect(rect)


def _point_within(rect: wx.Rect, *, dx: int = 2, dy: int = 2) -> tuple[int, int]:
    return rect.x + dx, rect.y + dy


@pytest.mark.integration
def test_marquee_drag_selects_multiple_rows(wx_app: wx.App) -> None:
    frame = wx.Frame(None)
    control = MarqueeDataViewListCtrl(frame, style=dv.DV_MULTIPLE | dv.DV_ROW_LINES)
    control.AppendTextColumn("Title", mode=dv.DATAVIEW_CELL_INERT, width=160)
    for index in range(5):
        control.AppendItem([f"Chat {index}"])

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(control, 1, wx.EXPAND)
    frame.SetSizer(sizer)
    frame.SetSize((320, 240))
    frame.Show()
    wx_app.Yield()

    first_rect = _row_rect(control, 0)
    third_rect = _row_rect(control, 2)

    down = wx.MouseEvent(wx.wxEVT_LEFT_DOWN)
    down.SetEventObject(control)
    down.SetPosition(_point_within(first_rect))
    control._on_left_down(down)

    move = wx.MouseEvent(wx.wxEVT_MOTION)
    move.SetEventObject(control)
    move.SetLeftDown(True)
    move.SetPosition(_point_within(third_rect))
    control._on_mouse_move(move)

    up = wx.MouseEvent(wx.wxEVT_LEFT_UP)
    up.SetEventObject(control)
    up.SetPosition(_point_within(third_rect))
    control._on_left_up(up)

    wx_app.Yield()

    selected_rows = [control.ItemToRow(item) for item in control.GetSelections()]
    frame.Destroy()

    assert len(selected_rows) >= 2
    assert 0 in selected_rows
    assert any(row in selected_rows for row in (1, 2))


@pytest.mark.integration
def test_marquee_handles_events_from_inner_window(wx_app: wx.App) -> None:
    frame = wx.Frame(None)
    control = MarqueeDataViewListCtrl(frame, style=dv.DV_MULTIPLE | dv.DV_ROW_LINES)
    control.AppendTextColumn("Title", mode=dv.DATAVIEW_CELL_INERT, width=160)
    for index in range(5):
        control.AppendItem([f"Chat {index}"])

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(control, 1, wx.EXPAND)
    frame.SetSizer(sizer)
    frame.SetSize((320, 240))
    frame.Show()
    wx_app.Yield()

    main_window = control.GetMainWindow()
    assert isinstance(main_window, wx.Window)
    assert main_window in control._marquee_sources

    first_rect = _row_rect(control, 0)
    third_rect = _row_rect(control, 2)

    def to_main(point: tuple[int, int]) -> tuple[int, int]:
        screen = control.ClientToScreen(point)
        return tuple(main_window.ScreenToClient(screen))

    down = wx.MouseEvent(wx.wxEVT_LEFT_DOWN)
    down.SetEventObject(main_window)
    down.SetPosition(to_main(_point_within(first_rect)))
    main_window.ProcessEvent(down)

    move = wx.MouseEvent(wx.wxEVT_MOTION)
    move.SetEventObject(main_window)
    move.SetLeftDown(True)
    move.SetPosition(to_main(_point_within(third_rect)))
    main_window.ProcessEvent(move)

    up = wx.MouseEvent(wx.wxEVT_LEFT_UP)
    up.SetEventObject(main_window)
    up.SetPosition(to_main(_point_within(third_rect)))
    main_window.ProcessEvent(up)

    wx_app.Yield()

    selected_rows = [control.ItemToRow(item) for item in control.GetSelections()]
    frame.Destroy()

    assert len(selected_rows) >= 2
    assert 0 in selected_rows
    assert any(row in selected_rows for row in (1, 2))
