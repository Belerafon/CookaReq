"""Common helper widgets and functions for UI components."""
from __future__ import annotations

from collections.abc import Callable

import wx

from ..i18n import _
from ..util.strings import coerce_text


def inherit_background(target: wx.Window, source: wx.Window | None) -> None:
    """Copy background colour from ``source`` to ``target`` when available."""
    if source is None:
        return
    setter = getattr(target, "SetBackgroundColour", None)
    getter = getattr(source, "GetBackgroundColour", None)
    if not callable(setter) or not callable(getter):
        return
    try:
        colour = getter()
    except Exception:
        return
    if colour is None:
        return
    if hasattr(colour, "IsOk"):
        try:
            if not colour.IsOk():
                system_colour = getattr(wx, "SystemSettings", None)
                if system_colour is None:
                    return
                try:
                    colour = system_colour.GetColour(wx.SYS_COLOUR_WINDOW)
                except Exception:
                    return
                if hasattr(colour, "IsOk") and not colour.IsOk():
                    return
        except Exception:
            return
    try:
        setter(colour)
    except Exception:
        return


def dip(window: wx.Window, value: int) -> int:
    """Convert a device-independent pixel ``value`` for ``window`` if possible."""
    converter = getattr(window, "FromDIP", None)
    if callable(converter):
        try:
            converted = converter(value)
        except Exception:
            return value
        try:
            return int(converted)
        except Exception:
            return value
    return value


def create_copy_button(
    parent: wx.Window,
    *,
    tooltip: str,
    fallback_label: str,
    handler: Callable[[wx.CommandEvent], None],
    size: int = 16,
) -> wx.Window:
    """Create a copy button reusing themed bitmaps when available."""
    icon_size = wx.Size(dip(parent, size), dip(parent, size))
    bitmap = wx.ArtProvider.GetBitmap(wx.ART_COPY, wx.ART_BUTTON, icon_size)
    if bitmap.IsOk():
        button: wx.Window = wx.BitmapButton(
            parent,
            bitmap=bitmap,
            style=wx.BU_EXACTFIT | wx.BORDER_NONE,
        )
    else:
        button = wx.Button(parent, label=fallback_label, style=wx.BU_EXACTFIT)
    inherit_background(button, parent)
    button.SetToolTip(tooltip)
    button.Bind(wx.EVT_BUTTON, handler)
    return button


class HelpStaticBox(wx.StaticBoxSizer):
    """A ``wx.StaticBoxSizer`` with a built-in help button.

    The button is appended to the first row inside the static box so it sits on
    the same line as the first added control. This avoids manual coordinate
    calculations and relies on sizer layout for positioning.
    """

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        help_text: str,
        on_help: Callable[[wx.Window, str], None] | None = None,
        *,
        orient: int = wx.VERTICAL,
        border: int = 5,
    ) -> None:
        """Create static box sizer with help button."""
        box = wx.StaticBox(parent, label=label)
        super().__init__(box, orient)

        self._border = border
        self._btn = wx.Button(box, label="?", style=wx.BU_EXACTFIT)
        self._help_text = help_text
        self._on_help: Callable[[wx.Window, str], None]
        if on_help is None:
            parent_window = parent

            def _default_help(anchor: wx.Window, message: str) -> None:
                show_help(parent_window, message, anchor=anchor)

            self._on_help = _default_help
        else:
            self._on_help = on_help
        self._btn.Bind(wx.EVT_BUTTON, self._handle_help)
        self._has_header = False

    def _wrap_first(self, item: wx.Window | wx.Sizer, flag: int) -> wx.Sizer:
        """Wrap the first item with the help button row."""
        self._has_header = True
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(item, 1, flag & ~wx.ALL, 0)
        row.Add(self._btn, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, self._border)
        return row

    def _handle_help(self, _evt: wx.CommandEvent) -> None:
        """Invoke the configured help callback for this static box."""
        self._on_help(self._btn, self._help_text)

    def Add(
        self,
        item: wx.Window | wx.Sizer,
        proportion: int = 0,
        flag: int = 0,
        border: int = 0,
        userData: object | None = None,
    ) -> wx.SizerItem:
        """Add an item to the sizer.

        The first added item is wrapped into a horizontal row alongside the
        help button. Subsequent items are forwarded to ``wx.StaticBoxSizer``
        unchanged.
        """
        if not self._has_header:
            row = self._wrap_first(item, flag)
            return super().Add(row, proportion, flag, border, userData)
        return super().Add(item, proportion, flag, border, userData)

    def Prepend(
        self,
        item: wx.Window | wx.Sizer,
        proportion: int = 0,
        flag: int = 0,
        border: int = 0,
        userData: object | None = None,
    ) -> wx.SizerItem:
        """Prepend an item, keeping the help button on the first row."""
        if not self._has_header:
            row = self._wrap_first(item, flag)
            return super().Prepend(row, proportion, flag, border, userData)
        return super().Insert(1, item, proportion, flag, border, userData)

    def Insert(
        self,
        index: int,
        item: wx.Window | wx.Sizer,
        proportion: int = 0,
        flag: int = 0,
        border: int = 0,
        userData: object | None = None,
    ) -> wx.SizerItem:
        """Insert an item at the given position.

        Indexing is performed as if the help row did not exist, so callers can
        treat this sizer like a regular ``StaticBoxSizer``.
        """
        if not self._has_header:
            row = self._wrap_first(item, flag)
            return super().Insert(index, row, proportion, flag, border, userData)
        return super().Insert(index + 1, item, proportion, flag, border, userData)


class AutoHeightListCtrl(wx.ListCtrl):
    """A ``wx.ListCtrl`` that reports a height matching its contents."""

    def __init__(
        self,
        *args,
        max_rows: int | None = None,
        extra_padding: int = 4,
        **kwargs,
    ) -> None:
        """Create list control limiting height to ``max_rows`` entries."""
        super().__init__(*args, **kwargs)
        self._max_rows = max_rows
        self._extra_padding = extra_padding
        self._row_height: int | None = None
        self._header_height: int | None = None

    def _measure_row_height(self) -> int:
        if self._row_height:
            return self._row_height
        rect = wx.Rect()
        if self.GetItemCount() and self.GetItemRect(0, rect, wx.LIST_RECT_BOUNDS):
            self._row_height = rect.height
        else:
            # Fallback to a reasonable approximation based on the current font.
            self._row_height = self.GetCharHeight() + 8
        return self._row_height

    def _measure_header_height(self) -> int:
        if self._header_height:
            return self._header_height
        if self.GetWindowStyleFlag() & wx.LC_NO_HEADER:
            self._header_height = 0
            return self._header_height
        header = self.GetHeaderCtrl()
        if header:
            self._header_height = header.GetSize().height
        else:
            # ``wx.LC_REPORT`` without a dedicated header still reserves a small
            # area above the items.  Mirror the behaviour with a font-based
            # estimate to avoid clipping.
            self._header_height = self.GetCharHeight() + 6
        return self._header_height

    def InvalidateBestSize(self) -> None:  # noqa: N802 - wxWidgets API casing
        """Reset cached measurements prior to a size recalculation."""
        self._row_height = None
        self._header_height = None
        super().InvalidateBestSize()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wxWidgets API casing
        """Return size matching list contents while honouring ``max_rows``."""
        best = super().DoGetBestSize()
        count = self.GetItemCount()
        if count <= 0:
            return wx.Size(best.width, 0)

        row_height = self._measure_row_height()
        rows = count
        if self._max_rows is not None:
            rows = min(rows, self._max_rows)
        header_height = self._measure_header_height()
        border = self.GetWindowBorderSize()
        vertical_border = border.height if border else 0
        height = header_height + row_height * rows + vertical_border * 2 + self._extra_padding
        return wx.Size(best.width, height)


def _client_display_rect_for(window: wx.Window | None) -> wx.Rect:
    """Return the usable display area for the monitor containing ``window``."""
    if window is not None:
        index = wx.Display.GetFromWindow(window)
        if index != wx.NOT_FOUND:
            return wx.Display(index).GetClientArea()
    x, y, width, height = wx.ClientDisplayRect()
    return wx.Rect(x, y, width, height)


def _calculate_popup_position(
    anchor_rect: wx.Rect,
    popup_size: wx.Size,
    display_rect: wx.Rect,
    pad: int = 8,
) -> tuple[int, int]:
    """Compute where to place a popup so it stays close to ``anchor_rect``."""
    width = popup_size.width
    height = popup_size.height

    anchor_left = anchor_rect.x
    anchor_top = anchor_rect.y
    anchor_right = anchor_rect.x + anchor_rect.width
    anchor_bottom = anchor_rect.y + anchor_rect.height

    display_left = display_rect.x
    display_top = display_rect.y
    display_right = display_rect.x + display_rect.width
    display_bottom = display_rect.y + display_rect.height

    def clamp_x(x: int) -> int:
        usable = display_rect.width - width - 2 * pad
        if usable < 0:
            return display_left + pad
        return max(display_left + pad, min(x, display_right - width - pad))

    def clamp_y(y: int) -> int:
        usable = display_rect.height - height - 2 * pad
        if usable < 0:
            return display_top + pad
        return max(display_top + pad, min(y, display_bottom - height - pad))

    space_right = display_right - anchor_right - pad
    if space_right >= width:
        return anchor_right + pad, clamp_y(anchor_top)

    space_left = anchor_left - display_left - pad
    if space_left >= width:
        return anchor_left - width - pad, clamp_y(anchor_top)

    space_below = display_bottom - anchor_bottom - pad
    if space_below >= height:
        return clamp_x(anchor_left), anchor_bottom + pad

    space_above = anchor_top - display_top - pad
    if space_above >= height:
        return clamp_x(anchor_left), anchor_top - height - pad

    return clamp_x(anchor_right + pad), clamp_y(anchor_top)


def _position_window_near_anchor(window: wx.Window, anchor: wx.Window | None) -> None:
    """Place ``window`` close to ``anchor`` while keeping it on-screen."""
    if anchor is None or not anchor.IsShownOnScreen():
        window.CenterOnParent()
        return

    anchor_rect = anchor.GetScreenRect()
    if anchor_rect.width <= 0 and anchor_rect.height <= 0:
        window.CenterOnParent()
        return

    display_rect = _client_display_rect_for(anchor)
    position = _calculate_popup_position(anchor_rect, window.GetSize(), display_rect)
    window.SetPosition(position)


_help_dialogs: dict[tuple[int, str], wx.Dialog] = {}


def _help_dialog_key(parent: wx.Window | None, message: str) -> tuple[int, str]:
    return (id(parent) if parent else 0, message)


def _create_help_dialog(
    parent: wx.Window | None,
    message: str,
    *,
    title: str,
) -> tuple[wx.Dialog, wx.TextCtrl]:
    dlg = wx.Dialog(
        parent,
        title=title,
        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP,
    )
    text = wx.TextCtrl(
        dlg,
        value=message,
        style=wx.TE_MULTILINE | wx.TE_READONLY,
    )
    text.SetMinSize(wx.Size(320, 160))
    text.SetInsertionPoint(0)

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(text, 1, wx.ALL | wx.EXPAND, 10)
    btns = dlg.CreateStdDialogButtonSizer(wx.OK)
    if btns:
        sizer.Add(btns, 0, wx.ALL | wx.ALIGN_CENTER, 5)
    dlg.SetSizerAndFit(sizer)
    dlg.Layout()
    return dlg, text


def show_help(
    parent: wx.Window,
    message: str,
    *,
    title: str | None = None,
    anchor: wx.Window | None = None,
) -> None:
    """Display a help dialog with ``message`` near the triggering control."""
    top_level = parent.GetTopLevelParent() if parent else None
    dialog_parent = top_level or parent
    key = _help_dialog_key(dialog_parent, message)
    dlg = _help_dialogs.get(key)
    if dlg and dlg:
        if not dlg.IsShown():
            dlg.Show()
        _position_window_near_anchor(dlg, anchor or parent)
        dlg.Raise()
        dlg.SetFocus()
        return

    dlg, text = _create_help_dialog(
        dialog_parent,
        message,
        title=title or _("Hint"),
    )

    def _destroy_dialog() -> None:
        _help_dialogs.pop(key, None)
        if dlg:
            dlg.Destroy()

    def _on_close(_evt: wx.CloseEvent) -> None:
        _destroy_dialog()

    def _on_ok(_evt: wx.CommandEvent) -> None:
        _destroy_dialog()

    dlg.Bind(wx.EVT_CLOSE, _on_close)
    ok_button = dlg.FindWindowById(wx.ID_OK)
    if ok_button:
        ok_button.Bind(wx.EVT_BUTTON, _on_ok)

    _help_dialogs[key] = dlg
    _position_window_near_anchor(dlg, anchor or parent)
    dlg.Show()
    dlg.Raise()
    dlg.SetFocus()


def make_help_button(
    parent: wx.Window,
    message: str,
    *,
    dialog_parent: wx.Window | None = None,
) -> wx.Button:
    """Return a small question-mark button displaying ``message`` when clicked.

    Parameters
    ----------
    parent:
        The container that owns the button.  This is typically the panel that
        hosts the form controls.
    message:
        Text shown inside the help popup.
    dialog_parent:
        Optional window that should own the help dialog.  Providing a
        top-level dialog avoids centering behaviour of intermediate container
        widgets (e.g. notebook pages) and guarantees the popup stays near the
        triggering button.
    """
    btn = wx.Button(parent, label="?", style=wx.BU_EXACTFIT)

    def _on_click(_evt: wx.CommandEvent) -> None:
        show_help(dialog_parent or parent, message, anchor=btn)

    btn.Bind(wx.EVT_BUTTON, _on_click)
    return btn


def format_error_message(error: object, *, fallback: str | None = None) -> str:
    """Normalize ``error`` objects for display in the UI.

    ``error`` may be a mapping with ``code``/``type`` and ``message`` fields,
    an exception instance or any other value.  Dictionaries are rendered as
    ``"code: message"`` pairs when possible.  If all attempts fail, returns the
    provided ``fallback`` or a localized "Unknown error" string.
    """

    def _normalise(part: object) -> str | None:
        if part in (None, ""):
            return None
        text = coerce_text(part, converters=(str,), truncate=500)
        if text is None:
            return None
        cleaned = text.strip()
        return cleaned or None

    if isinstance(error, dict):
        code_text = _normalise(error.get("code") or error.get("type"))
        message_text = _normalise(error.get("message"))
        parts = [part for part in (code_text, message_text) if part]
        if parts:
            return ": ".join(parts)
    else:
        text = _normalise(error)
        if text is not None:
            return text

    if fallback is not None:
        return fallback
    return _("Unknown error")
