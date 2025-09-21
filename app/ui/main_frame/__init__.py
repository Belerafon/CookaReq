"""Main frame package providing the application window."""

from ...confirm import confirm
from ...i18n import _
from ...mcp.controller import MCPController
from ..document_dialog import DocumentPropertiesDialog
from ..error_dialog import show_error_dialog
from ..settings_dialog import SettingsDialog
from .frame import MainFrame
from .logging import WxLogHandler

__all__ = [
    "MainFrame",
    "WxLogHandler",
    "SettingsDialog",
    "DocumentPropertiesDialog",
    "MCPController",
    "confirm",
    "_",
    "show_error_dialog",
]
