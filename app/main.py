"""Application entry point for CookaReq."""

import wx
from .ui.main_frame import MainFrame


def main() -> None:
    """Run wx application with the main frame."""
    app = wx.App()
    frame = MainFrame(parent=None)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":  # pragma: no cover
    main()
