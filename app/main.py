"""Application entry point for CookaReq."""

import logging
import wx
from .ui.main_frame import MainFrame


def main() -> None:
    """Run wx application with the main frame."""
    logging.basicConfig(level=logging.INFO)
    app = wx.App()
    frame = MainFrame(parent=None)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":  # pragma: no cover
    main()
