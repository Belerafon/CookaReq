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

    The helper reduces repetitive layout code around ``wx.StaticBox`` by
    automatically placing a small ``?`` button in the top-right corner.
    Clicking the button calls ``on_help`` with the provided ``help_text``.

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
        Border width around the help button; default is ``5``.

    Returns
    -------
    Tuple[wx.StaticBox, wx.StaticBoxSizer]
        The created static box and its sizer.
    """
    box = wx.StaticBox(parent, label=label)
    sizer = wx.StaticBoxSizer(box, orient)
    btn = wx.Button(box, label="?", style=wx.BU_EXACTFIT)
    btn.Bind(wx.EVT_BUTTON, lambda _evt: on_help(help_text))
    header = wx.BoxSizer(wx.HORIZONTAL)
    header.AddStretchSpacer()
    header.Add(btn, 0)
    sizer.Add(header, 0, wx.ALIGN_RIGHT | wx.ALL, border)
    return box, sizer
