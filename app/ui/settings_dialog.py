"""Dialog for application settings with MCP controls."""

from gettext import gettext as _
from importlib import resources

import wx

from app.llm.client import LLMClient, LLMSettings
from app.mcp.client import MCPClient
from app.mcp.controller import MCPController, MCPStatus
from app.mcp.settings import MCPSettings


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
        api_base: str,
        model: str,
        api_key: str,
        timeout: int,
        host: str,
        port: int,
        base_path: str,
        require_token: bool,
        token: str,
    ) -> None:
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
        gen_sizer.Add(self._open_last, 0, wx.ALL, 5)
        gen_sizer.Add(self._remember_sort, 0, wx.ALL, 5)
        lang_sizer = wx.BoxSizer(wx.HORIZONTAL)
        lang_sizer.Add(wx.StaticText(general, label=_("Language")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        lang_sizer.Add(self._language_choice, 1, wx.ALIGN_CENTER_VERTICAL)
        gen_sizer.Add(lang_sizer, 0, wx.ALL | wx.EXPAND, 5)
        general.SetSizer(gen_sizer)

        # LLM/Agent settings ---------------------------------------------
        llm = wx.Panel(nb)
        self._api_base = wx.TextCtrl(llm, value=api_base)
        self._model = wx.TextCtrl(llm, value=model)
        self._api_key = wx.TextCtrl(llm, value=api_key, style=wx.TE_PASSWORD)
        self._timeout = wx.SpinCtrl(llm, min=1, max=9999, initial=timeout)

        self._check_llm = wx.Button(llm, label=_("Check LLM"))
        self._check_tools = wx.Button(llm, label=_("Check tools"))
        self._llm_status = wx.StaticText(llm, label=_("not checked"))
        self._tools_status = wx.StaticText(llm, label=_("not checked"))

        self._check_llm.Bind(wx.EVT_BUTTON, self._on_check_llm)
        self._check_tools.Bind(wx.EVT_BUTTON, self._on_check_tools)

        llm_sizer = wx.BoxSizer(wx.VERTICAL)
        base_sz = wx.BoxSizer(wx.HORIZONTAL)
        base_sz.Add(wx.StaticText(llm, label=_("API base")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        base_sz.Add(self._api_base, 1, wx.ALIGN_CENTER_VERTICAL)
        llm_sizer.Add(base_sz, 0, wx.ALL | wx.EXPAND, 5)
        model_sz = wx.BoxSizer(wx.HORIZONTAL)
        model_sz.Add(wx.StaticText(llm, label=_("Model")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        model_sz.Add(self._model, 1, wx.ALIGN_CENTER_VERTICAL)
        llm_sizer.Add(model_sz, 0, wx.ALL | wx.EXPAND, 5)
        key_sz = wx.BoxSizer(wx.HORIZONTAL)
        key_sz.Add(wx.StaticText(llm, label=_("API key")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        key_sz.Add(self._api_key, 1, wx.ALIGN_CENTER_VERTICAL)
        llm_sizer.Add(key_sz, 0, wx.ALL | wx.EXPAND, 5)
        timeout_sz = wx.BoxSizer(wx.HORIZONTAL)
        timeout_sz.Add(wx.StaticText(llm, label=_("Timeout")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        timeout_sz.Add(self._timeout, 1, wx.ALIGN_CENTER_VERTICAL)
        llm_sizer.Add(timeout_sz, 0, wx.ALL | wx.EXPAND, 5)
        btn_sz = wx.BoxSizer(wx.HORIZONTAL)
        llm_btn_sz = wx.BoxSizer(wx.VERTICAL)
        llm_btn_sz.Add(self._check_llm, 0, wx.BOTTOM, 2)
        llm_btn_sz.Add(self._llm_status, 0, wx.ALIGN_CENTER)
        tools_btn_sz = wx.BoxSizer(wx.VERTICAL)
        tools_btn_sz.Add(self._check_tools, 0, wx.BOTTOM, 2)
        tools_btn_sz.Add(self._tools_status, 0, wx.ALIGN_CENTER)
        btn_sz.Add(llm_btn_sz, 0, wx.RIGHT, 5)
        btn_sz.Add(tools_btn_sz, 0)
        llm_sizer.Add(btn_sz, 0, wx.ALL, 5)
        llm.SetSizer(llm_sizer)

        # MCP settings ----------------------------------------------------
        mcp = wx.Panel(nb)
        self._host = wx.TextCtrl(mcp, value=host)
        self._port = wx.SpinCtrl(mcp, min=1, max=65535, initial=port)
        self._base_path = wx.TextCtrl(mcp, value=base_path)
        self._require_token = wx.CheckBox(mcp, label=_("Require token"))
        self._require_token.SetValue(require_token)
        self._token = wx.TextCtrl(mcp, value=token)
        self._token.Enable(require_token)

        self._mcp = MCPController()
        start_stop_label = _("Stop MCP") if self._mcp.is_running() else _("Start MCP")
        self._start_stop = wx.Button(mcp, label=start_stop_label)
        self._check = wx.Button(mcp, label=_("Check MCP"))
        self._status = wx.StaticText(mcp, label=_("not running"))

        self._require_token.Bind(wx.EVT_CHECKBOX, self._on_toggle_token)
        self._start_stop.Bind(wx.EVT_BUTTON, self._on_start_stop)
        self._check.Bind(wx.EVT_BUTTON, self._on_check)

        mcp_sizer = wx.BoxSizer(wx.VERTICAL)
        host_sz = wx.BoxSizer(wx.HORIZONTAL)
        host_sz.Add(wx.StaticText(mcp, label=_("Host")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        host_sz.Add(self._host, 1, wx.ALIGN_CENTER_VERTICAL)
        mcp_sizer.Add(host_sz, 0, wx.ALL | wx.EXPAND, 5)
        port_sz = wx.BoxSizer(wx.HORIZONTAL)
        port_sz.Add(wx.StaticText(mcp, label=_("Port")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        port_sz.Add(self._port, 1, wx.ALIGN_CENTER_VERTICAL)
        mcp_sizer.Add(port_sz, 0, wx.ALL | wx.EXPAND, 5)
        base_sz = wx.BoxSizer(wx.HORIZONTAL)
        base_sz.Add(wx.StaticText(mcp, label=_("Path")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        base_sz.Add(self._base_path, 1, wx.ALIGN_CENTER_VERTICAL)
        mcp_sizer.Add(base_sz, 0, wx.ALL | wx.EXPAND, 5)
        mcp_sizer.Add(self._require_token, 0, wx.ALL, 5)
        token_sz = wx.BoxSizer(wx.HORIZONTAL)
        token_sz.Add(wx.StaticText(mcp, label=_("Token")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        token_sz.Add(self._token, 1, wx.ALIGN_CENTER_VERTICAL)
        mcp_sizer.Add(token_sz, 0, wx.ALL | wx.EXPAND, 5)
        btn_sz = wx.BoxSizer(wx.HORIZONTAL)
        btn_sz.Add(self._start_stop, 0, wx.RIGHT, 5)
        btn_sz.Add(self._check, 0)
        mcp_sizer.Add(btn_sz, 0, wx.ALL, 5)
        mcp_sizer.Add(self._status, 0, wx.ALL, 5)
        mcp.SetSizer(mcp_sizer)

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
    def _on_toggle_token(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._token.Enable(self._require_token.GetValue())

    def _update_start_stop_label(self) -> None:
        label = _("Stop MCP") if self._mcp.is_running() else _("Start MCP")
        self._start_stop.SetLabel(label)

    def _current_llm_settings(self) -> LLMSettings:
        return LLMSettings(
            api_base=self._api_base.GetValue(),
            model=self._model.GetValue(),
            api_key=self._api_key.GetValue(),
            timeout=self._timeout.GetValue(),
        )

    def _current_settings(self) -> MCPSettings:
        return MCPSettings(
            host=self._host.GetValue(),
            port=self._port.GetValue(),
            base_path=self._base_path.GetValue(),
            require_token=self._require_token.GetValue(),
            token=self._token.GetValue(),
        )

    def _on_start_stop(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        settings = self._current_settings()
        if self._mcp.is_running():
            self._mcp.stop()
            self._status.SetLabel(_("not running"))
        else:
            self._mcp.start(settings)
            self._status.SetLabel(_("not running"))
        self._update_start_stop_label()

    def _on_check_llm(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        client = LLMClient(settings=self._current_llm_settings())
        result = client.check_llm()
        label = _("ok") if result.get("ok") else _("error")
        self._llm_status.SetLabel(label)

    def _on_check_tools(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        client = MCPClient(settings=self._current_settings())
        result = client.check_tools()
        label = _("ok") if result.get("ok") else _("error")
        self._tools_status.SetLabel(label)

    def _on_check(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        status = self._mcp.check(self._current_settings())
        mapping = {
            MCPStatus.NOT_RUNNING: _("not running"),
            MCPStatus.READY: _("ready"),
            MCPStatus.ERROR: _("error"),
        }
        self._status.SetLabel(mapping[status])

    # ------------------------------------------------------------------
    def get_values(self) -> tuple[
        bool,
        bool,
        str,
        str,
        str,
        str,
        int,
        str,
        int,
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
            self._api_base.GetValue(),
            self._model.GetValue(),
            self._api_key.GetValue(),
            self._timeout.GetValue(),
            self._host.GetValue(),
            self._port.GetValue(),
            self._base_path.GetValue(),
            self._require_token.GetValue(),
            self._token.GetValue(),
        )

