"""Dialog for application settings with MCP controls."""

import threading
from collections.abc import Callable
from importlib import resources

import wx

from ..i18n import _
from ..log import logger
from ..llm.client import LLMClient
from ..mcp.client import MCPClient
from ..mcp.controller import MCPController, MCPStatus
from ..settings import LLMSettings, MCPSettings
from .helpers import format_error_message, make_help_button

GENERAL_HELP: dict[str, str] = {
    "open_last": _(
        "Automatically reopen the most recently used requirements folder on startup.\n"
        "Disable to always choose a folder manually.",
    ),
    "remember_sort": _(
        "Remember the last column and direction used to sort requirements.\n"
        "Keeps the list ordering consistent between sessions.",
    ),
    "language": _(
        "Language for menus and dialogs.\n"
        "Changes apply after restarting CookaReq.",
    ),
}


LLM_HELP: dict[str, str] = {
    "base_url": _(
        "Base URL of the LLM API. Example: https://api.openai.com/v1\n"
        "Required; defines where requests are sent.",
    ),
    "model": _(
        "LLM model name. Example: gpt-4-turbo\n"
        "Required; selects which model to use.",
    ),
    "api_key": _(
        "LLM access key. Example: sk-XXXX\n"
        "Required when the service needs authentication.",
    ),
    "max_retries": _(
        "Number of times to retry a failed HTTP request. Example: 3\n"
        "Optional; defaults to 3 retries.",
    ),
    "timeout_minutes": _(
        "HTTP request timeout in minutes. Example: 1\n"
        "Optional; defaults to 60 minutes.",
    ),
    "stream": _(
        "Stream partial responses from the LLM as they arrive.\n"
        "Disable to wait for the full reply before showing it.",
    ),
    "check_llm": _(
        "Send a test request to the configured LLM using the current settings.\n"
        "Use this to verify credentials and network connectivity.",
    ),
    "check_tools": _(
        "Contact the MCP server with the current connection settings and"
        " list the available tools.\n"
        "Ensures the agent integration is configured correctly.",
    ),
}

MCP_HELP: dict[str, str] = {
    "auto_start": _(
        "Start the MCP server automatically when CookaReq launches.",
    ),
    "host": _(
        "Hostname for the MCP server. Example: 127.0.0.1\n"
        "Required; defines where to run the server.",
    ),
    "port": _(
        "MCP server port. Example: 8123\nRequired field.",
    ),
    "base_path": _(
        "Base folder with requirements. Example: /tmp/reqs\n"
        "Required; the server serves files from this directory.",
    ),
    "log_dir": _(
        "Directory for MCP request logs. Example: /var/log/cookareq\n"
        "Leave empty to store logs in the standard application log folder.",
    ),
    "require_token": _(
        "When enabled, the server requires an authentication token.",
    ),
    "token": _(
        "Access token for MCP. Example: secret123\n"
        "Required when \"Require token\" is enabled.",
    ),
    "start": _(
        "Launch the MCP server in the background using the current"
        " connection settings.",
    ),
    "stop": _(
        "Stop the MCP server instance that was started from CookaReq.",
    ),
    "check": _(
        "Connect to the MCP server and report whether it is reachable.\n"
        "Displays diagnostic information about the running instance.",
    ),
    "status": _(
        "Shows whether the MCP server is currently running according to"
        " CookaReq and the result of the last check.",
    ),
}


def available_translations() -> list[tuple[str, str]]:
    """Return list of (language_code, display_name) for available translations."""
    langs: list[tuple[str, str]] = []
    locale_root = resources.files("app") / "locale"
    for entry in locale_root.iterdir():
        if entry.is_dir():
            code = entry.name
            info = wx.Locale.FindLanguageInfo(code)
            name = info.Description if info else code
            langs.append((code, name))
    return langs


class SettingsDialog(wx.Dialog):
    """Dialog providing general preferences and MCP server controls."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        open_last: bool,
        remember_sort: bool,
        language: str,
        base_url: str,
        model: str,
        api_key: str,
        max_retries: int,
        timeout_minutes: int,
        stream: bool,
        auto_start: bool,
        host: str,
        port: int,
        base_path: str,
        log_dir: str | None,
        require_token: bool,
        token: str,
    ) -> None:
        """Create settings dialog with LLM and MCP configuration."""
        super().__init__(parent, title=_("Settings"))

        # General settings -------------------------------------------------
        self._languages = available_translations()
        choices = [name for _, name in self._languages]
        try:
            idx = [code for code, _ in self._languages].index(language)
        except ValueError:
            idx = 0

        nb = wx.Notebook(self)
        general = wx.Panel(nb)
        self._open_last = wx.CheckBox(general, label=_("Open last folder on startup"))
        self._open_last.SetValue(open_last)
        self._remember_sort = wx.CheckBox(general, label=_("Remember sort order"))
        self._remember_sort.SetValue(remember_sort)
        self._language_choice = wx.Choice(general, choices=choices)
        self._language_choice.SetSelection(idx)

        gen_sizer = wx.BoxSizer(wx.VERTICAL)
        open_last_sz = wx.BoxSizer(wx.HORIZONTAL)
        open_last_sz.Add(self._open_last, 0, wx.ALIGN_CENTER_VERTICAL)
        open_last_sz.Add(
            make_help_button(general, GENERAL_HELP["open_last"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        gen_sizer.Add(open_last_sz, 0, wx.ALL | wx.EXPAND, 5)

        remember_sort_sz = wx.BoxSizer(wx.HORIZONTAL)
        remember_sort_sz.Add(self._remember_sort, 0, wx.ALIGN_CENTER_VERTICAL)
        remember_sort_sz.Add(
            make_help_button(
                general,
                GENERAL_HELP["remember_sort"],
                dialog_parent=self,
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        gen_sizer.Add(remember_sort_sz, 0, wx.ALL | wx.EXPAND, 5)
        lang_sizer = wx.BoxSizer(wx.HORIZONTAL)
        lang_sizer.Add(
            wx.StaticText(general, label=_("Language")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        lang_sizer.Add(self._language_choice, 1, wx.ALIGN_CENTER_VERTICAL)
        lang_sizer.Add(
            make_help_button(general, GENERAL_HELP["language"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        gen_sizer.Add(lang_sizer, 0, wx.ALL | wx.EXPAND, 5)
        general.SetSizer(gen_sizer)

        # LLM/Agent settings ---------------------------------------------
        llm = wx.Panel(nb)
        self._base_url = wx.TextCtrl(llm, value=base_url)
        self._model = wx.TextCtrl(llm, value=model)
        self._api_key = wx.TextCtrl(llm, value=api_key, style=wx.TE_PASSWORD)
        self._max_retries = wx.SpinCtrl(llm, min=0, max=10, initial=max_retries)
        self._timeout = wx.SpinCtrl(llm, min=1, max=9999, initial=timeout_minutes)
        self._stream = wx.CheckBox(llm, label=_("Stream"))
        self._stream.SetValue(stream)

        self._check_llm = wx.Button(llm, label=_("Check LLM"))
        self._check_tools = wx.Button(llm, label=_("Check tools"))
        self._llm_status = wx.StaticText(llm, label=_("not checked"))
        self._tools_status = wx.StaticText(llm, label=_("not checked"))

        self._check_llm.Bind(wx.EVT_BUTTON, self._on_check_llm)
        self._check_tools.Bind(wx.EVT_BUTTON, self._on_check_tools)

        llm_sizer = wx.BoxSizer(wx.VERTICAL)
        base_sz = wx.BoxSizer(wx.HORIZONTAL)

        base_sz.Add(
            wx.StaticText(llm, label=_("API base")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        base_sz.Add(self._base_url, 1, wx.ALIGN_CENTER_VERTICAL)
        base_sz.Add(
            make_help_button(llm, LLM_HELP["base_url"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        llm_sizer.Add(base_sz, 0, wx.ALL | wx.EXPAND, 5)
        model_sz = wx.BoxSizer(wx.HORIZONTAL)
        model_sz.Add(
            wx.StaticText(llm, label=_("Model")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        model_sz.Add(self._model, 1, wx.ALIGN_CENTER_VERTICAL)
        model_sz.Add(
            make_help_button(llm, LLM_HELP["model"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        llm_sizer.Add(model_sz, 0, wx.ALL | wx.EXPAND, 5)
        key_sz = wx.BoxSizer(wx.HORIZONTAL)
        key_sz.Add(
            wx.StaticText(llm, label=_("API key")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        key_sz.Add(self._api_key, 1, wx.ALIGN_CENTER_VERTICAL)
        key_sz.Add(
            make_help_button(llm, LLM_HELP["api_key"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        llm_sizer.Add(key_sz, 0, wx.ALL | wx.EXPAND, 5)
        retries_sz = wx.BoxSizer(wx.HORIZONTAL)
        retries_sz.Add(
            wx.StaticText(llm, label=_("Max retries")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        retries_sz.Add(self._max_retries, 1, wx.ALIGN_CENTER_VERTICAL)
        retries_sz.Add(
            make_help_button(llm, LLM_HELP["max_retries"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        llm_sizer.Add(retries_sz, 0, wx.ALL | wx.EXPAND, 5)
        timeout_sz = wx.BoxSizer(wx.HORIZONTAL)
        timeout_sz.Add(
            wx.StaticText(llm, label=_("Timeout (min)")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        timeout_sz.Add(self._timeout, 1, wx.ALIGN_CENTER_VERTICAL)
        timeout_sz.Add(
            make_help_button(llm, LLM_HELP["timeout_minutes"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        llm_sizer.Add(timeout_sz, 0, wx.ALL | wx.EXPAND, 5)
        stream_sz = wx.BoxSizer(wx.HORIZONTAL)
        stream_sz.Add(self._stream, 0, wx.ALIGN_CENTER_VERTICAL)
        stream_sz.Add(
            make_help_button(llm, LLM_HELP["stream"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        llm_sizer.Add(stream_sz, 0, wx.ALL | wx.EXPAND, 5)
        btn_sz = wx.BoxSizer(wx.HORIZONTAL)
        llm_btn_sz = wx.BoxSizer(wx.VERTICAL)
        llm_btn_sz.Add(
            self._make_control_with_help(
                parent=llm,
                control=self._check_llm,
                help_text=LLM_HELP["check_llm"],
            ),
            0,
            wx.BOTTOM,
            2,
        )
        llm_btn_sz.Add(self._llm_status, 0, wx.ALIGN_CENTER)
        tools_btn_sz = wx.BoxSizer(wx.VERTICAL)
        tools_btn_sz.Add(
            self._make_control_with_help(
                parent=llm,
                control=self._check_tools,
                help_text=LLM_HELP["check_tools"],
            ),
            0,
            wx.BOTTOM,
            2,
        )
        tools_btn_sz.Add(self._tools_status, 0, wx.ALIGN_CENTER)
        btn_sz.Add(llm_btn_sz, 0, wx.RIGHT, 5)
        btn_sz.Add(tools_btn_sz, 0)
        llm_sizer.Add(btn_sz, 0, wx.ALL, 5)
        llm.SetSizer(llm_sizer)

        # MCP settings ----------------------------------------------------
        mcp = wx.Panel(nb)
        self._auto_start = wx.CheckBox(mcp, label=_("Run MCP server on startup"))
        self._auto_start.SetValue(auto_start)
        self._host = wx.TextCtrl(mcp, value=host)
        self._port = wx.SpinCtrl(mcp, min=1, max=65535, initial=port)
        self._base_path = wx.TextCtrl(mcp, value=base_path)
        log_dir_value = str(log_dir) if log_dir else ""
        self._log_dir = wx.TextCtrl(mcp, value=log_dir_value)
        self._require_token = wx.CheckBox(mcp, label=_("Require token"))
        self._require_token.SetValue(require_token)
        self._token = wx.TextCtrl(mcp, value=token)
        self._token.Enable(require_token)

        self._mcp = MCPController()
        self._start = wx.Button(mcp, label=_("Start MCP"))
        self._stop = wx.Button(mcp, label=_("Stop MCP"))
        self._check = wx.Button(mcp, label=_("Check MCP"))
        self._status = wx.StaticText(mcp)
        help_txt = wx.StaticText(
            mcp,
            label=_(
                "MCP is a local server providing tools for requirement management used by agents and the LLM.",
            ),
        )
        help_txt.Wrap(300)

        self._require_token.Bind(wx.EVT_CHECKBOX, self._on_toggle_token)
        self._start.Bind(wx.EVT_BUTTON, self._on_start)
        self._stop.Bind(wx.EVT_BUTTON, self._on_stop)
        self._check.Bind(wx.EVT_BUTTON, self._on_check)

        mcp_sizer = wx.BoxSizer(wx.VERTICAL)
        auto_start_sz = wx.BoxSizer(wx.HORIZONTAL)
        auto_start_sz.Add(self._auto_start, 0, wx.ALIGN_CENTER_VERTICAL)
        auto_start_sz.Add(
            make_help_button(mcp, MCP_HELP["auto_start"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        mcp_sizer.Add(auto_start_sz, 0, wx.ALL | wx.EXPAND, 5)
        host_sz = wx.BoxSizer(wx.HORIZONTAL)
        host_sz.Add(
            wx.StaticText(mcp, label=_("Host")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        host_sz.Add(self._host, 1, wx.ALIGN_CENTER_VERTICAL)
        host_sz.Add(
            make_help_button(mcp, MCP_HELP["host"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        mcp_sizer.Add(host_sz, 0, wx.ALL | wx.EXPAND, 5)
        port_sz = wx.BoxSizer(wx.HORIZONTAL)
        port_sz.Add(
            wx.StaticText(mcp, label=_("Port")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        port_sz.Add(self._port, 1, wx.ALIGN_CENTER_VERTICAL)
        port_sz.Add(
            make_help_button(mcp, MCP_HELP["port"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        mcp_sizer.Add(port_sz, 0, wx.ALL | wx.EXPAND, 5)
        base_sz = wx.BoxSizer(wx.HORIZONTAL)
        base_sz.Add(
            wx.StaticText(mcp, label=_("Path")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        base_sz.Add(self._base_path, 1, wx.ALIGN_CENTER_VERTICAL)
        base_sz.Add(
            make_help_button(mcp, MCP_HELP["base_path"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        mcp_sizer.Add(base_sz, 0, wx.ALL | wx.EXPAND, 5)
        log_sz = wx.BoxSizer(wx.HORIZONTAL)
        log_sz.Add(
            wx.StaticText(mcp, label=_("Log directory")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        log_sz.Add(self._log_dir, 1, wx.ALIGN_CENTER_VERTICAL)
        log_sz.Add(
            make_help_button(mcp, MCP_HELP["log_dir"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        mcp_sizer.Add(log_sz, 0, wx.ALL | wx.EXPAND, 5)
        token_toggle_sz = wx.BoxSizer(wx.HORIZONTAL)
        token_toggle_sz.Add(self._require_token, 0, wx.ALIGN_CENTER_VERTICAL)
        token_toggle_sz.Add(
            make_help_button(mcp, MCP_HELP["require_token"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        mcp_sizer.Add(token_toggle_sz, 0, wx.ALL, 5)
        token_sz = wx.BoxSizer(wx.HORIZONTAL)
        token_sz.Add(
            wx.StaticText(mcp, label=_("Token")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        token_sz.Add(self._token, 1, wx.ALIGN_CENTER_VERTICAL)
        token_sz.Add(
            make_help_button(mcp, MCP_HELP["token"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )
        mcp_sizer.Add(token_sz, 0, wx.ALL | wx.EXPAND, 5)
        btn_sz = wx.BoxSizer(wx.HORIZONTAL)
        btn_sz.Add(
            self._make_control_with_help(
                parent=mcp,
                control=self._start,
                help_text=MCP_HELP["start"],
            ),
            0,
            wx.RIGHT,
            5,
        )
        btn_sz.Add(
            self._make_control_with_help(
                parent=mcp,
                control=self._stop,
                help_text=MCP_HELP["stop"],
            ),
            0,
            wx.RIGHT,
            5,
        )
        btn_sz.Add(
            self._make_control_with_help(
                parent=mcp,
                control=self._check,
                help_text=MCP_HELP["check"],
            ),
            0,
        )
        mcp_sizer.Add(btn_sz, 0, wx.ALL, 5)
        mcp_sizer.Add(
            self._make_control_with_help(
                parent=mcp,
                control=self._status,
                help_text=MCP_HELP["status"],
            ),
            0,
            wx.ALL,
            5,
        )
        mcp_sizer.Add(help_txt, 0, wx.ALL | wx.EXPAND, 5)
        mcp.SetSizer(mcp_sizer)
        self._update_mcp_controls()

        # Notebook --------------------------------------------------------
        nb.AddPage(general, _("General"))
        nb.AddPage(llm, _("LLM/Agent"))
        nb.AddPage(mcp, _("MCP"))

        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(nb, 1, wx.EXPAND | wx.ALL, 5)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            dlg_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizerAndFit(dlg_sizer)

    # ------------------------------------------------------------------
    def _on_toggle_token(
        self,
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
        self._token.Enable(self._require_token.GetValue())

    def _update_mcp_controls(self) -> None:
        running = self._mcp.is_running()
        self._start.Enable(not running)
        self._stop.Enable(running)
        status = _("running") if running else _("not running")
        self._status.SetLabel(f"{_('Status')}: {status}")

    def _make_control_with_help(
        self,
        *,
        parent: wx.Window,
        control: wx.Window,
        help_text: str,
        border: int = 5,
    ) -> wx.BoxSizer:
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(control, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(
            make_help_button(parent, help_text, dialog_parent=self),
            0,
            wx.LEFT | wx.ALIGN_CENTER_VERTICAL,
            border,
        )
        return row

    def _current_llm_settings(self) -> LLMSettings:
        return LLMSettings(
            base_url=self._base_url.GetValue(),
            model=self._model.GetValue(),
            api_key=self._api_key.GetValue() or None,
            max_retries=self._max_retries.GetValue(),
            timeout_minutes=self._timeout.GetValue(),
            stream=self._stream.GetValue(),
        )

    def _current_settings(self) -> MCPSettings:
        return MCPSettings(
            auto_start=self._auto_start.GetValue(),
            host=self._host.GetValue(),
            port=self._port.GetValue(),
            base_path=self._base_path.GetValue(),
            log_dir=self._log_dir.GetValue().strip() or None,
            require_token=self._require_token.GetValue(),
            token=self._token.GetValue(),
        )

    def _on_start(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        settings = self._current_settings()
        self._mcp.start(settings)
        self._update_mcp_controls()

    def _on_stop(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._mcp.stop()
        self._update_mcp_controls()

    def _on_check_llm(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        settings = self._current_llm_settings()

        def task() -> tuple[bool, str | None]:
            client = LLMClient(settings=settings)
            result = client.check_llm()
            ok = bool(result.get("ok"))
            if ok:
                return True, None
            return False, format_error_message(result.get("error"))

        self._run_background_check(
            button=self._check_llm,
            status_label=self._llm_status,
            task=task,
        )

    def _on_check_tools(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        settings = self._current_settings()

        def task() -> tuple[bool, str | None]:
            client = MCPClient(settings=settings, confirm=lambda _m: True)
            result = client.check_tools()
            ok = bool(result.get("ok"))
            if ok:
                return True, None
            return False, format_error_message(result.get("error"))

        self._run_background_check(
            button=self._check_tools,
            status_label=self._tools_status,
            task=task,
        )

    def _on_check(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        result = self._mcp.check(self._current_settings())
        status = result.status
        running = status != MCPStatus.NOT_RUNNING
        self._start.Enable(not running)
        self._stop.Enable(running)
        label_map = {
            MCPStatus.READY: _("ready"),
            MCPStatus.ERROR: _("error"),
            MCPStatus.NOT_RUNNING: _("not running"),
        }
        label = label_map[status]
        self._status.SetLabel(f"{_('Status')}: {label}")
        self.Layout()
        wx.MessageBox(
            f"{_('Status')}: {label}\n{result.message}",
            _("Check MCP"),
        )

    # ------------------------------------------------------------------
    def _run_background_check(
        self,
        *,
        button: wx.Button,
        status_label: wx.StaticText,
        task: Callable[[], tuple[bool, str | None]],
    ) -> None:
        status_label.SetLabel("...")
        status_label.SetToolTip(None)
        button.Enable(False)

        app = wx.GetApp()
        is_main_loop_running = bool(
            app and getattr(app, "IsMainLoopRunning", lambda: False)()
        )
        finished = threading.Event()
        result_holder: dict[str, tuple[bool, str | None]] = {}

        def apply_result(ok: bool, tooltip: str | None) -> None:
            button.Enable(True)
            status_label.SetLabel(_("ok") if ok else _("error"))
            status_label.SetToolTip(tooltip if tooltip else None)
            if not ok:
                label_getter = getattr(button, "GetLabelText", None)
                button_label = (
                    label_getter() if callable(label_getter) else button.GetLabel()
                )
                message = tooltip or _("Unknown error")
                logger.warning("%s failed: %s", button_label, message)

        def worker() -> None:
            try:
                ok, tooltip = task()
            except Exception as exc:  # pragma: no cover - defensive
                ok = False
                tooltip = format_error_message(exc)

            if is_main_loop_running:
                wx.CallAfter(apply_result, ok, tooltip)
            else:
                result_holder["value"] = (ok, tooltip)
                finished.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        if not is_main_loop_running:
            finished.wait()
            ok, tooltip = result_holder.get("value", (False, None))
            apply_result(ok, tooltip)

    # ------------------------------------------------------------------
    def get_values(
        self,
    ) -> tuple[
        bool,
        bool,
        str,
        str,
        str,
        str,
        int,
        int,
        bool,
        bool,
        str,
        int,
        str,
        str,
        bool,
        str,
    ]:
        """Return configured options."""
        lang_code = self._languages[self._language_choice.GetSelection()][0]
        return (
            self._open_last.GetValue(),
            self._remember_sort.GetValue(),
            lang_code,
            self._base_url.GetValue(),
            self._model.GetValue(),
            self._api_key.GetValue(),
            self._max_retries.GetValue(),
            self._timeout.GetValue(),
            self._stream.GetValue(),
            self._auto_start.GetValue(),
            self._host.GetValue(),
            self._port.GetValue(),
            self._base_path.GetValue(),
            self._log_dir.GetValue().strip(),
            self._require_token.GetValue(),
            self._token.GetValue(),
        )
