"""Session-level helpers extracted from :mod:`panel`."""
from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from collections.abc import Callable, Mapping

from ...llm.spec import SYSTEM_PROMPT
from ...llm.tokenizer import (
    TokenCountResult,
    combine_token_counts,
    count_text_tokens,
)
from ..chat_entry import ChatConversation, ChatEntry, count_context_message_tokens
from .confirm_preferences import RequirementConfirmPreference
from .token_usage import ContextTokenBreakdown, TOKEN_UNAVAILABLE_LABEL, format_token_quantity


@dataclass(slots=True)
class SessionConfig:
    token_model_resolver: Callable[[], str | None]
    context_window_resolver: Callable[[], int | None]


class SessionController:
    """Encapsulate token accounting and preference handling."""

    def __init__(
        self,
        *,
        config: SessionConfig,
        token_counter: Callable[[str, str | None], TokenCountResult] | None = None,
    ) -> None:
        self._config = config
        self._system_token_cache: dict[tuple[str | None, tuple[str, ...]], TokenCountResult] = {}
        # Allow callers (and tests) to override the tokenizer.  This keeps token
        # accounting in sync with the monkeypatched functions used elsewhere in
        # the panel so totals remain deterministic during GUI checks.
        self._count_tokens = token_counter or (
            lambda text, model=None: count_text_tokens(text, model=model)
        )

    # ------------------------------------------------------------------
    def set_token_counter(
        self, counter: Callable[[str, str | None], TokenCountResult] | None
    ) -> None:
        """Replace the token counting function used for accounting."""

        if counter is None:
            self._count_tokens = lambda text, model=None: count_text_tokens(
                text, model=model
            )
        else:
            self._count_tokens = counter

    # ------------------------------------------------------------------
    def token_model(self) -> str | None:
        resolver = self._config.token_model_resolver
        try:
            model = resolver()
        except Exception:  # pragma: no cover - defensive
            return None
        if not isinstance(model, str):
            return None
        text = model.strip()
        return text or None

    # ------------------------------------------------------------------
    def context_token_limit(self) -> int | None:
        resolver = self._config.context_window_resolver
        if resolver is None:
            return None
        try:
            value = resolver()
        except Exception:  # pragma: no cover - defensive
            return None
        if value is None:
            return None
        try:
            numeric = int(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None
        return numeric if numeric > 0 else None

    # ------------------------------------------------------------------
    def compute_context_token_breakdown(
        self,
        conversation: ChatConversation | None,
        *,
        handle_context_messages: tuple[Mapping[str, object], ...] | None = None,
        pending_entry: ChatEntry | None = None,
        active_handle_prompt_tokens: TokenCountResult | None = None,
        custom_system_prompt: str | None = None,
    ) -> ContextTokenBreakdown:
        model = self.token_model()
        system_parts = [SYSTEM_PROMPT]
        if custom_system_prompt:
            system_parts.append(custom_system_prompt)
        system_key = (model, tuple(part for part in system_parts if part))
        system_tokens = self._system_token_cache.get(system_key)
        if system_tokens is None:
            if system_key[1]:
                system_tokens = combine_token_counts(
                    [self._count_tokens(part, model) for part in system_key[1]]
                )
            else:
                system_tokens = TokenCountResult.exact(0, model=model)
            self._system_token_cache[system_key] = system_tokens

        history_counts: list[TokenCountResult] = []
        if conversation is not None:
            for entry in conversation.entries:
                if pending_entry is not None and entry is pending_entry:
                    continue
                if entry.prompt:
                    history_counts.append(entry.ensure_prompt_token_usage(model))
                if entry.response:
                    history_counts.append(entry.ensure_response_token_usage(model))
                if hasattr(entry, "ensure_tool_messages"):
                    entry.ensure_tool_messages()
                tool_messages = getattr(entry, "tool_messages", None)
                if tool_messages:
                    for message in tool_messages:
                        if not isinstance(message, Mapping):
                            continue
                        history_counts.append(
                            count_context_message_tokens(message, model)
                        )
        if history_counts:
            history_tokens = combine_token_counts(history_counts)
        else:
            history_tokens = TokenCountResult.exact(0, model=model)

        context_messages = handle_context_messages or ()
        if context_messages:
            cached_entry: ChatEntry | None = None
            if conversation is not None:
                for entry in reversed(conversation.entries):
                    if entry.context_messages == context_messages:
                        cached_entry = entry
                        break
            if cached_entry is not None:
                context_tokens = cached_entry.ensure_context_token_usage(
                    model, messages=context_messages
                )
            else:
                context_tokens = combine_token_counts(
                    count_context_message_tokens(message, model)
                    for message in context_messages
                )
        else:
            context_tokens = TokenCountResult.exact(0, model=model)

        prompt_tokens = active_handle_prompt_tokens
        if prompt_tokens is None:
            prompt_tokens = TokenCountResult.exact(0, model=model)

        return ContextTokenBreakdown(
            system=system_tokens,
            history=history_tokens,
            context=context_tokens,
            prompt=prompt_tokens,
        )

    # ------------------------------------------------------------------
    def format_context_percentage(self, tokens: TokenCountResult) -> str:
        limit = self.context_token_limit()
        if limit is None or limit <= 0:
            return TOKEN_UNAVAILABLE_LABEL
        if tokens.tokens is None:
            return TOKEN_UNAVAILABLE_LABEL
        percentage = (tokens.tokens / limit) * 100
        if percentage >= 10:
            formatted = f"{percentage:.0f}%"
        elif percentage >= 1:
            formatted = f"{percentage:.1f}%"
        else:
            formatted = f"{percentage:.2f}%"
        if tokens.approximate:
            return f"~{formatted}"
        return formatted

    # ------------------------------------------------------------------
    def format_tokens_for_status(self, tokens: TokenCountResult) -> str:
        tokens_text = format_token_quantity(tokens)
        limit = self.context_token_limit()
        if limit is not None:
            limit_tokens = TokenCountResult.exact(
                limit,
                model=tokens.model,
            )
            limit_text = format_token_quantity(limit_tokens)
            tokens_text = f"{tokens_text} / {limit_text}"
        return tokens_text

    # ------------------------------------------------------------------
    def normalize_confirm_preference(
        self, value: RequirementConfirmPreference | str | None
    ) -> RequirementConfirmPreference:
        if isinstance(value, RequirementConfirmPreference):
            preference = value
        elif isinstance(value, str):
            preference = RequirementConfirmPreference.PROMPT
            with suppress(ValueError, KeyError):
                preference = RequirementConfirmPreference(value)
            if preference is RequirementConfirmPreference.PROMPT and value in RequirementConfirmPreference.__members__:
                preference = RequirementConfirmPreference[value]
        else:
            preference = RequirementConfirmPreference.PROMPT

        if preference is RequirementConfirmPreference.CHAT_ONLY:
            return RequirementConfirmPreference.PROMPT
        return preference


__all__ = ["SessionConfig", "SessionController"]
