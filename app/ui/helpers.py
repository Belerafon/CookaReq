"""Common helper widgets and functions for UI components."""
from __future__ import annotations

from typing import Callable

import wx


def create_help_static_box(
    parent: wx.Window,
    label: str,
    help_text: str,
    on_help: Callable[[str], None],
    *,
    orient: int = wx.VERTICAL,
    border: int = 5,
) -> tuple[wx.StaticBox, wx.StaticBoxSizer]:
    """Create a ``wx.StaticBox`` with a question button that shows a hint.

    The button is anchored in the top‑right corner of the box so it does not
    consume additional layout space. ``on_help`` is called with ``help_text``
    when the button is pressed.

    Parameters
    ----------
    parent: wx.Window
        Parent widget for the static box.
    label: str
        Title of the static box.
    help_text: str
        Message to display when the help button is clicked.
    on_help: Callable[[str], None]
        Callback invoked when the help button is pressed; typically shows a
        dialog with the hint text.
    orient: int, optional
        Orientation for ``wx.StaticBoxSizer``; ``wx.VERTICAL`` by default.
    border: int, optional
        Distance from the box edge to the help button; default is ``5``.

    Returns
    -------
    Tuple[wx.StaticBox, wx.StaticBoxSizer]
        The created static box and its sizer.
    """
    box = wx.StaticBox(parent, label=label)
    sizer = wx.StaticBoxSizer(box, orient)
    btn = wx.Button(box, label="?", style=wx.BU_EXACTFIT)
    btn.Bind(wx.EVT_BUTTON, lambda _evt: on_help(help_text))

    def _reposition(_evt: wx.Event | None = None) -> None:
        """Place the help button in the box's top-right corner."""
        w, _ = box.GetClientSize()
        bw, _ = btn.GetSize()
        btn.SetPosition((w - bw - border, border))

    box.Bind(wx.EVT_SIZE, _reposition)
    wx.CallAfter(_reposition)

    return box, sizer
