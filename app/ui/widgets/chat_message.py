"""Widgets used to render chat transcript entries."""

from __future__ import annotations

import json
from typing import Any, Sequence

import wx

from ...i18n import _


def _blend_colour(base: wx.Colour, other: wx.Colour, weight: float) -> wx.Colour:
    weight = max(0.0, min(weight, 1.0))
    return wx.Colour(
        int(base.Red() * (1.0 - weight) + other.Red() * weight),
        int(base.Green() * (1.0 - weight) + other.Green() * weight),
        int(base.Blue() * (1.0 - weight) + other.Blue() * weight),
    )


class MessageBubble(wx.Panel):
    """Simple chat bubble with copy support and automatic wrapping."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        role_label: str,
        timestamp: str,
        text: str,
        align: str,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetDoubleBuffered(True)

        self._text_value = text
        self._wrap_width = 0
        self._content_padding = self.FromDIP(12)
        self._copy_menu_id = wx.Window.NewControlId()
        self.Bind(wx.EVT_MENU, self._on_copy, id=self._copy_menu_id)

        user_highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        user_text = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
        agent_bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        agent_text = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)

        if align == "right":
            bubble_bg = user_highlight
            bubble_fg = user_text
            meta_colour = _blend_colour(user_text, wx.Colour(255, 255, 255), 0.4)
        else:
            bubble_bg = agent_bg
            bubble_fg = agent_text
            meta_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)

        outer = wx.BoxSizer(wx.HORIZONTAL)
        if align == "right":
            outer.AddStretchSpacer()

        bubble = wx.Panel(self, style=wx.BORDER_NONE)
        bubble.SetBackgroundColour(bubble_bg)
        bubble.SetForegroundColour(bubble_fg)
        bubble.SetDoubleBuffered(True)
        bubble_sizer = wx.BoxSizer(wx.VERTICAL)
        bubble.SetSizer(bubble_sizer)

        header_text = role_label if not timestamp else f"{role_label} • {timestamp}"
        header = wx.StaticText(bubble, label=header_text)
        header.SetForegroundColour(meta_colour)
        header_font = header.GetFont()
        if header_font.IsOk():
            header_font.MakeSmaller()
            header.SetFont(header_font)
        bubble_sizer.Add(
            header,
            0,
            wx.TOP | wx.LEFT | wx.RIGHT,
            self._content_padding,
        )

        self._text = wx.StaticText(bubble, label=text)
        self._text.SetForegroundColour(bubble_fg)
        self._text.Wrap(self.FromDIP(320))
        bubble_sizer.Add(
            self._text,
            0,
            wx.EXPAND | wx.ALL,
            self._content_padding,
        )

        bubble.Bind(wx.EVT_SIZE, self._on_bubble_resize)
        for widget in (self, bubble, self._text):
            widget.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)

        outer.Add(bubble, 0, wx.EXPAND)
        if align == "left":
            outer.AddStretchSpacer()

        self.SetSizer(outer)

    def _on_bubble_resize(self, event: wx.SizeEvent) -> None:
        event.Skip()
        width = event.GetSize().width - 2 * self._content_padding
        width = max(width, self.FromDIP(120))
        if abs(width - self._wrap_width) > self.FromDIP(4):
            self._wrap_width = width
            self._text.Wrap(width)

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        menu = wx.Menu()
        menu.Append(self._copy_menu_id, _("Copy message"))
        self.PopupMenu(menu)
        menu.Destroy()
        event.Skip(False)

    def _on_copy(self, _event: wx.CommandEvent) -> None:
        if not self._text_value:
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self._text_value))
            finally:
                wx.TheClipboard.Close()


class TranscriptMessagePanel(wx.Panel):
    """Compact chat entry view with optional tool details."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        prompt: str,
        response: str,
        tool_results: Sequence[Any] | None = None,
        prompt_timestamp: str = "",
        response_timestamp: str = "",
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetDoubleBuffered(True)

        outer = wx.BoxSizer(wx.VERTICAL)
        padding = self.FromDIP(4)

        user_bubble = MessageBubble(
            self,
            role_label=_("You"),
            timestamp=prompt_timestamp,
            text=prompt,
            align="right",
        )
        outer.Add(user_bubble, 0, wx.EXPAND | wx.ALL, padding)

        agent_bubble = MessageBubble(
            self,
            role_label=_("Agent"),
            timestamp=response_timestamp,
            text=response,
            align="left",
        )
        outer.Add(agent_bubble, 0, wx.EXPAND | wx.ALL, padding)

        if tool_results:
            outer.Add(
                self._create_tool_results_section(tool_results),
                0,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                padding,
            )

        self.SetSizer(outer)

    def _create_tool_results_section(
        self, tool_results: Sequence[Any]
    ) -> wx.Window:
        container = wx.Panel(self)
        container.SetBackgroundColour(self.GetBackgroundColour())
        sizer = wx.BoxSizer(wx.VERTICAL)
        container.SetSizer(sizer)

        label = wx.StaticText(container, label=_("Tool results"))
        label_font = label.GetFont()
        if label_font.IsOk():
            label_font.MakeBold()
            label.SetFont(label_font)
        sizer.Add(label, 0, wx.BOTTOM, self.FromDIP(2))

        for tool_index, payload in enumerate(tool_results, start=1):
            pane_label = self._build_pane_label(payload, tool_index)
            pane = wx.CollapsiblePane(
                container,
                label=pane_label,
                style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
            )
            sizer.Add(pane, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(4))
            body = pane.GetPane()
            body_sizer = wx.BoxSizer(wx.VERTICAL)
            body.SetSizer(body_sizer)
            body.SetBackgroundColour(container.GetBackgroundColour())

            status = wx.StaticText(body, label=self._describe_tool_status(payload))
            body_sizer.Add(status, 0, wx.BOTTOM, self.FromDIP(2))

            arguments = self._extract_arguments(payload)
            if arguments is not None:
                args_label = wx.StaticText(body, label=_("Arguments:"))
                args_font = args_label.GetFont()
                if args_font.IsOk():
                    args_font.MakeBold()
                    args_label.SetFont(args_font)
                body_sizer.Add(args_label, 0, wx.BOTTOM, self.FromDIP(1))
                body_sizer.Add(
                    self._create_json_text(body, arguments),
                    0,
                    wx.EXPAND | wx.BOTTOM,
                    self.FromDIP(4),
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
            body_sizer.Add(controls, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(2))

            body_sizer.Add(
                self._create_json_text(body, json_text, is_preformatted=True),
                0,
                wx.EXPAND | wx.BOTTOM,
                self.FromDIP(4),
            )

        return container

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
            style=(
                wx.TE_MULTILINE
                | wx.TE_READONLY
                | wx.TE_DONTWRAP
                | wx.TE_NO_VSCROLL
                | wx.BORDER_SIMPLE
            ),
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
