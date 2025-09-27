"""Confirmation preference helpers for the agent chat panel."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any
from collections.abc import Callable

import wx

from ...confirm import (
    ConfirmDecision,
    RequirementUpdatePrompt,
    reset_requirement_update_preference,
)

logger = logging.getLogger("cookareq.ui.agent_chat_panel.confirm")


class RequirementConfirmPreference(Enum):
    """Supported confirmation policies for agent-driven operations."""

    PROMPT = "prompt"
    CHAT_ONLY = "chat_only"
    NEVER = "never"


class ConfirmPreferencesMixin:
    """Shared logic for persisting and applying confirmation preferences."""

    _persist_confirm_preference_callback: Callable[[str], None] | None
    _confirm_preference: RequirementConfirmPreference
    _persistent_confirm_preference: RequirementConfirmPreference
    _confirm_choice: wx.Choice | None
    _confirm_choice_index: dict[RequirementConfirmPreference, int]
    _confirm_choice_entries: tuple[tuple[RequirementConfirmPreference, str], ...]
    _suppress_confirm_choice_events: bool
    _auto_confirm_overrides: dict[str, Any] | None

    def _normalize_confirm_preference(
        self,
        value: RequirementConfirmPreference | str | None,
    ) -> RequirementConfirmPreference:
        """Convert *value* into a recognised confirmation preference."""

        if isinstance(value, RequirementConfirmPreference):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text == RequirementConfirmPreference.NEVER.value:
                return RequirementConfirmPreference.NEVER
            if text == RequirementConfirmPreference.CHAT_ONLY.value:
                return RequirementConfirmPreference.CHAT_ONLY
        return RequirementConfirmPreference.PROMPT

    def _persist_confirm_preference(
        self,
        preference: RequirementConfirmPreference,
    ) -> None:
        callback = getattr(self, "_persist_confirm_preference_callback", None)
        if callback is None:
            return
        try:
            callback(preference.value)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to persist agent confirmation preference to config",
            )

    def _update_confirm_choice_ui(
        self,
        preference: RequirementConfirmPreference,
    ) -> None:
        choice = getattr(self, "_confirm_choice", None)
        if choice is None:
            return
        index = getattr(self, "_confirm_choice_index", {}).get(preference)
        if index is None or choice.GetSelection() == index:
            return
        self._suppress_confirm_choice_events = True
        try:
            choice.SetSelection(index)
        finally:
            self._suppress_confirm_choice_events = False

    def _set_confirm_preference(
        self,
        preference: RequirementConfirmPreference,
        *,
        persist: bool,
        update_ui: bool = True,
    ) -> None:
        if preference is RequirementConfirmPreference.CHAT_ONLY:
            self._confirm_preference = preference
        else:
            self._persistent_confirm_preference = preference
            self._confirm_preference = preference
            if persist:
                self._persist_confirm_preference(preference)
        if update_ui:
            self._update_confirm_choice_ui(self._confirm_preference)
        if preference is RequirementConfirmPreference.PROMPT:
            reset_requirement_update_preference()

    def _confirm_override_kwargs(self) -> dict[str, Any]:
        if self._confirm_preference is RequirementConfirmPreference.PROMPT:
            return {}
        overrides = getattr(self, "_auto_confirm_overrides", None)
        if overrides is None:

            def _auto_confirm(_message: str) -> bool:
                return True

            def _auto_confirm_update(
                _prompt: RequirementUpdatePrompt,
            ) -> ConfirmDecision:
                return ConfirmDecision.YES

            overrides = {
                "confirm_override": _auto_confirm,
                "confirm_requirement_update_override": _auto_confirm_update,
            }
            self._auto_confirm_overrides = overrides
        return overrides

    def _on_confirm_choice(self, event: wx.CommandEvent) -> None:
        if getattr(self, "_suppress_confirm_choice_events", False):
            event.Skip()
            return
        selection = event.GetSelection()
        entries = getattr(self, "_confirm_choice_entries", ())
        if not isinstance(selection, int) or not (0 <= selection < len(entries)):
            choice = event.GetEventObject()
            if hasattr(choice, "GetSelection"):
                selection = choice.GetSelection()
        if not isinstance(selection, int) or not (0 <= selection < len(entries)):
            event.Skip()
            return
        preference = entries[selection][0]
        persist = preference is not RequirementConfirmPreference.CHAT_ONLY
        self._set_confirm_preference(
            preference,
            persist=persist,
            update_ui=False,
        )
        event.Skip()

    def _on_active_conversation_changed(
        self,
        previous_id: str | None,
        new_id: str | None,
    ) -> None:
        if previous_id == new_id:
            return
        if self._confirm_preference is RequirementConfirmPreference.CHAT_ONLY:
            self._set_confirm_preference(
                self._persistent_confirm_preference,
                persist=False,
            )

    @property
    def confirmation_preference(self) -> str:
        """Return current confirmation policy as a string key."""

        return self._confirm_preference.value


__all__ = [
    "ConfirmPreferencesMixin",
    "RequirementConfirmPreference",
]
