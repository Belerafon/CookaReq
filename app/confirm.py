"""Confirmation callback registry for user interactions."""

from typing import Callable

ConfirmCallback = Callable[[str], bool]
_callback: ConfirmCallback | None = None


def set_confirm(callback: ConfirmCallback) -> None:
    """Register confirmation *callback* returning True to proceed."""
    global _callback
    _callback = callback


def confirm(message: str) -> bool:
    """Invoke registered confirmation callback with *message*.
    Raises ``RuntimeError`` if no callback configured.
    """
    if _callback is None:
        raise RuntimeError("Confirmation callback not configured")
    return _callback(message)


def wx_confirm(message: str) -> bool:
    """GUI confirmation dialog using wxWidgets."""

    import wx  # type: ignore

    from .i18n import _

    try:
        parent = wx.GetActiveWindow()
    except AttributeError:  # pragma: no cover - stubs may omit helper
        parent = None
    if not parent:
        try:
            windows = wx.GetTopLevelWindows()
        except AttributeError:  # pragma: no cover - stubs may omit helper
            windows = []
        parent = windows[0] if windows else None

    style = wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
    dialog = wx.MessageDialog(parent, message, _("Confirm"), style=style)
    try:
        result = dialog.ShowModal()
    finally:
        dialog.Destroy()

    return result in {wx.ID_YES, wx.YES, wx.ID_OK, wx.OK}


def auto_confirm(_message: str) -> bool:
    """Confirmation callback that always returns True."""
    return True
