import pytest
import wx

import app.ui.widgets.height_limited_dataview as height_module
from app.ui.widgets.height_limited_dataview import HeightLimitedDataViewListCtrl


pytestmark = pytest.mark.gui


def _create_control(
    parent: wx.Window,
    *,
    height_limit: int | None,
    rows: int = 10,
) -> HeightLimitedDataViewListCtrl:
    control = HeightLimitedDataViewListCtrl(parent, height_limit=height_limit)
    control.AppendTextColumn("RID", width=parent.FromDIP(120))
    control.AppendTextColumn("Title", width=parent.FromDIP(200))
    for index in range(rows):
        control.AppendItem([f"REQ-{index:04d}", f"Requirement {index}"])
    return control


@pytest.mark.integration
def test_limit_caps_reported_height(wx_app: wx.App) -> None:
    frame = wx.Frame(None)
    limit = frame.FromDIP(180)
    try:
        control = _create_control(frame, height_limit=limit, rows=60)
        raw_size = wx.Size(frame.FromDIP(400), frame.FromDIP(640))

        limited = control._limit_height(raw_size)

        assert limited.height == limit
        assert limited.width == raw_size.width
    finally:
        frame.Destroy()


@pytest.mark.integration
def test_limit_respects_effective_minimum(wx_app: wx.App) -> None:
    frame = wx.Frame(None)
    min_height = frame.FromDIP(140)
    try:
        control = _create_control(frame, height_limit=frame.FromDIP(60), rows=5)
        control.SetMinSize(wx.Size(-1, min_height))

        limited = control._limit_height(wx.Size(frame.FromDIP(320), frame.FromDIP(20)))

        assert limited.height == min_height
    finally:
        frame.Destroy()


@pytest.mark.integration
def test_limit_can_be_disabled(wx_app: wx.App) -> None:
    frame = wx.Frame(None)
    try:
        control = _create_control(frame, height_limit=frame.FromDIP(120), rows=50)
        capped = control._limit_height(wx.Size(frame.FromDIP(320), frame.FromDIP(520)))
        control.SetHeightLimit(None)
        restored = control._limit_height(wx.Size(frame.FromDIP(320), frame.FromDIP(520)))

        assert capped.height < restored.height
        assert restored.height == frame.FromDIP(520)
    finally:
        frame.Destroy()


@pytest.mark.integration
def test_limit_constrains_control_height(
    monkeypatch: pytest.MonkeyPatch, wx_app: wx.App
) -> None:
    frame = wx.Frame(None)
    try:
        control = _create_control(frame, height_limit=frame.FromDIP(220), rows=40)
        observed: dict[str, wx.Size] = {}

        def fake_limit(
            self: HeightLimitedDataViewListCtrl, size: wx.Size
        ) -> wx.Size:
            observed["input"] = wx.Size(size.width, size.height)
            return wx.Size(size.width, frame.FromDIP(150))

        monkeypatch.setattr(
            height_module.HeightLimitedDataViewListCtrl,
            "_limit_height",
            fake_limit,
        )

        control.DoSetSize(0, 0, frame.FromDIP(360), frame.FromDIP(480))

        assert observed["input"].height == frame.FromDIP(480)
        assert control.GetSize().height == frame.FromDIP(150)
    finally:
        frame.Destroy()
