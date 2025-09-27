"""Settings dialog integration for the main frame."""

from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ...settings import LLMSettings, MCPSettings

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameSettingsMixin:
    """Handle opening and applying application settings."""

    def on_open_settings(
        self: "MainFrame",
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
        """Display settings dialog and apply changes."""

        from . import SettingsDialog

        dlg = SettingsDialog(
            self,
            open_last=self.auto_open_last,
            remember_sort=self.remember_sort,
            language=self.language,
            base_url=self.llm_settings.base_url,
            model=self.llm_settings.model,
            message_format=getattr(
                self.llm_settings.message_format,
                "value",
                self.llm_settings.message_format,
            ),
            api_key=self.llm_settings.api_key or "",
            max_retries=self.llm_settings.max_retries,
            max_context_tokens=self.llm_settings.max_context_tokens,
            timeout_minutes=self.llm_settings.timeout_minutes,
            use_custom_temperature=self.llm_settings.use_custom_temperature,
            temperature=self.llm_settings.temperature,
            stream=self.llm_settings.stream,
            auto_start=self.mcp_settings.auto_start,
            host=self.mcp_settings.host,
            port=self.mcp_settings.port,
            base_path=self.mcp_settings.base_path,
            log_dir=self.mcp_settings.log_dir,
            require_token=self.mcp_settings.require_token,
            token=self.mcp_settings.token,
        )
        if dlg.ShowModal() == wx.ID_OK:
            (
                auto_open_last,
                remember_sort,
                language,
                base_url,
                model,
                message_format,
                api_key,
                max_retries,
                max_context_tokens,
                timeout_minutes,
                use_custom_temperature,
                temperature,
                stream,
                auto_start,
                host,
                port,
                base_path,
                log_dir,
                require_token,
                token,
            ) = dlg.get_values()
            previous_language = self.language
            language_changed = previous_language != language
            self.auto_open_last = auto_open_last
            self.remember_sort = remember_sort
            self.language = language
            previous_mcp = self.mcp_settings
            self.llm_settings = LLMSettings(
                base_url=base_url,
                model=model,
                message_format=message_format,
                api_key=api_key or None,
                max_retries=max_retries,
                max_context_tokens=max_context_tokens,
                timeout_minutes=timeout_minutes,
                use_custom_temperature=use_custom_temperature,
                temperature=temperature,
                stream=stream,
            )
            self.mcp_settings = MCPSettings(
                auto_start=auto_start,
                host=host,
                port=port,
                base_path=base_path,
                log_dir=log_dir or None,
                require_token=require_token,
                token=token,
            )
            self.config.set_auto_open_last(self.auto_open_last)
            self.config.set_remember_sort(self.remember_sort)
            self.config.set_language(self.language)
            self.config.set_llm_settings(self.llm_settings)
            self.config.set_mcp_settings(self.mcp_settings)
            auto_start_changed = (
                previous_mcp.auto_start != self.mcp_settings.auto_start
            )
            server_config_changed = (
                previous_mcp.model_dump(exclude={"auto_start"})
                != self.mcp_settings.model_dump(exclude={"auto_start"})
            )
            if auto_start_changed:
                if self.mcp_settings.auto_start:
                    self.mcp.start(self.mcp_settings)
                else:
                    self.mcp.stop()
            elif self.mcp_settings.auto_start and server_config_changed:
                self.mcp.stop()
                self.mcp.start(self.mcp_settings)
            if language_changed:
                self._apply_language()
        dlg.Destroy()
