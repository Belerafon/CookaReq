import pytest


pytestmark = pytest.mark.gui


def test_error_dialog_copy_button(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.error_dialog import ErrorDialog

    copied: dict[str, str] = {}

    class DummyClipboard:
        def __init__(self) -> None:
            self.opened = False

        def Open(self) -> bool:  # noqa: N802 - wx naming convention
            self.opened = True
            return True

        def Close(self) -> None:  # noqa: N802 - wx naming convention
            self.opened = False

        def SetData(self, data) -> None:  # noqa: N802 - wx naming convention
            copied["text"] = data.GetText()

    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    dialog = ErrorDialog(None, "Sample message", title="Error")
    try:
        dialog._on_copy(None)
    finally:
        dialog.Destroy()

    assert copied["text"] == "Sample message"
