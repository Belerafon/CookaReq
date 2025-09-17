"""Widgets used to render chat transcript entries."""

from __future__ import annotations

import json
from typing import Any, Sequence

import wx

from ...i18n import _


class TranscriptMessagePanel(wx.Panel):
    """Card-style container with collapsible tool result sections."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        index: int,
        prompt: str,
        response: str,
        tool_results: Sequence[Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetDoubleBuffered(True)

        outer = wx.BoxSizer(wx.VERTICAL)
        card = wx.Panel(self, style=wx.BORDER_THEME)
        card.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        card_sizer = wx.BoxSizer(wx.VERTICAL)
        card.SetSizer(card_sizer)

        padding = self.FromDIP(8)
        inner_padding = wx.LEFT | wx.RIGHT

        prompt_label = wx.StaticText(card, label=f"{index}. " + _("You:"))
        card_sizer.Add(prompt_label, 0, wx.TOP | inner_padding, padding)
        card_sizer.Add(
            self._create_message_text(card, prompt),
            0,
            wx.EXPAND | inner_padding | wx.BOTTOM,
            padding,
        )

        agent_label = wx.StaticText(card, label=_("Agent:"))
        card_sizer.Add(agent_label, 0, wx.TOP | inner_padding, padding)
        card_sizer.Add(
            self._create_message_text(card, response),
            0,
            wx.EXPAND | inner_padding | wx.BOTTOM,
            padding,
        )

        if tool_results:
            tools_label = wx.StaticText(card, label=_("Tool results"))
            card_sizer.Add(tools_label, 0, wx.TOP | inner_padding, padding)
            for tool_index, payload in enumerate(tool_results, start=1):
                pane_label = self._build_pane_label(payload, tool_index)
                pane = wx.CollapsiblePane(
                    card,
                    label=pane_label,
                    style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
                )
                card_sizer.Add(pane, 0, wx.EXPAND | wx.ALL, padding)
                body = pane.GetPane()
                body_sizer = wx.BoxSizer(wx.VERTICAL)
                body.SetSizer(body_sizer)
                body.SetBackgroundColour(card.GetBackgroundColour())

                status = wx.StaticText(body, label=self._describe_tool_status(payload))
                body_sizer.Add(status, 0, wx.BOTTOM | wx.TOP, padding // 2)

                arguments = self._extract_arguments(payload)
                if arguments is not None:
                    args_label = wx.StaticText(body, label=_("Arguments:"))
                    body_sizer.Add(args_label, 0, wx.BOTTOM, padding // 4)
                    body_sizer.Add(
                        self._create_json_text(body, arguments),
                        0,
                        wx.EXPAND | wx.BOTTOM,
                        padding,
                    )

                json_text = self._format_json(payload)
                controls = wx.BoxSizer(wx.HORIZONTAL)
                controls.AddStretchSpacer()
                copy_button = wx.Button(body, label=_("Copy JSON"))
                copy_button.Bind(
                    wx.EVT_BUTTON,
                    lambda event, text=json_text: self._copy_to_clipboard(text),
                )
                controls.Add(copy_button, 0)
                body_sizer.Add(controls, 0, wx.EXPAND | wx.BOTTOM, padding // 2)

                body_sizer.Add(
                    self._create_json_text(body, json_text, is_preformatted=True),
                    0,
                    wx.EXPAND | wx.BOTTOM,
                    padding,
                )

        outer.Add(card, 0, wx.EXPAND | wx.ALL, self.FromDIP(4))
        self.SetSizer(outer)

    def _create_message_text(self, parent: wx.Window, value: str) -> wx.TextCtrl:
        ctrl = wx.TextCtrl(
            parent,
            value=value,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP | wx.BORDER_NONE,
        )
        ctrl.SetBackgroundColour(parent.GetBackgroundColour())
        ctrl.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        ctrl.SetMinSize(wx.Size(-1, self.FromDIP(64)))
        return ctrl

    def _create_json_text(
        self,
        parent: wx.Window,
        value: str,
        *,
        is_preformatted: bool = False,
    ) -> wx.TextCtrl:
        ctrl = wx.TextCtrl(
            parent,
            value=value,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.BORDER_SIMPLE,
        )
        ctrl.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        ctrl.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        ctrl.SetMinSize(wx.Size(-1, self.FromDIP(96 if is_preformatted else 72)))
        font = wx.SystemSettings.GetFont(wx.SYS_ANSI_FIXED_FONT)
        if font.IsOk():
            ctrl.SetFont(font)
        return ctrl

    def _build_pane_label(self, payload: Any, index: int) -> str:
        status_prefix = "✓" if self._is_ok(payload) else "⚠"
        name = self._extract_tool_name(payload)
        if name:
            return f"{status_prefix} {name}"
        return _("{status} Tool #{index}").format(
            status=status_prefix,
            index=index,
        )

    def _describe_tool_status(self, payload: Any) -> str:
        status = _("Success") if self._is_ok(payload) else _("Error")
        error = self._extract_error(payload)
        if error:
            return _("Status: {status} — {details}").format(status=status, details=error)
        return _("Status: {status}").format(status=status)

    @staticmethod
    def _is_ok(payload: Any) -> bool:
        if isinstance(payload, dict):
            return bool(payload.get("ok", False))
        return False

    @staticmethod
    def _extract_tool_name(payload: Any) -> str | None:
        if isinstance(payload, dict):
            name = payload.get("tool_name") or payload.get("name")
            if name:
                return str(name)
        return None

    @staticmethod
    def _extract_arguments(payload: Any) -> str | None:
        if isinstance(payload, dict):
            arguments = payload.get("tool_arguments")
            if arguments is None:
                return None
            try:
                return json.dumps(arguments, ensure_ascii=False, indent=2, sort_keys=True)
            except (TypeError, ValueError):
                return str(arguments)
        return None

    @staticmethod
    def _extract_error(payload: Any) -> str | None:
        if isinstance(payload, dict):
            error = payload.get("error")
            if not error:
                return None
            if isinstance(error, dict):
                message = error.get("message")
                if message:
                    return str(message)
            return str(error)
        return None

    @staticmethod
    def _format_json(payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        except (TypeError, ValueError):
            return str(payload)

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        if not text:
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
            finally:
                wx.TheClipboard.Close()
