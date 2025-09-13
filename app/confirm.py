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

    return (
        wx.MessageBox(
            message,
            _("Confirm"),
            style=wx.YES_NO | wx.ICON_WARNING,
        )
        == wx.YES
    )


def auto_confirm(_message: str) -> bool:
    """Confirmation callback that always returns True."""
    return True
