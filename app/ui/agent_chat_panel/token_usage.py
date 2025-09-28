"""Token usage helpers for the agent chat panel."""

from __future__ import annotations

from dataclasses import dataclass

from ...i18n import _
from ...llm.tokenizer import TokenCountResult, combine_token_counts


TOKEN_UNAVAILABLE_LABEL = _("n/a")


@dataclass(frozen=True)
class ContextTokenBreakdown:
    """Aggregated token usage for the prompt context."""

    system: TokenCountResult
    history: TokenCountResult
    context: TokenCountResult
    prompt: TokenCountResult

    @property
    def total(self) -> TokenCountResult:
        """Return combined token usage across all components."""

        return combine_token_counts(
            [self.system, self.history, self.context, self.prompt]
        )


def format_token_quantity(tokens: TokenCountResult) -> str:
    """Return human readable representation for ``tokens``."""

    if tokens.tokens is None:
        return TOKEN_UNAVAILABLE_LABEL
    quantity = tokens.tokens / 1000 if tokens.tokens else 0.0
    label = f"{quantity:.2f} k tokens"
    return f"~{label}" if tokens.approximate else label


def summarize_token_usage(
    tokens: TokenCountResult, limit: int | None
) -> str:
    """Return formatted usage string with optional context *limit*."""

    used = format_token_quantity(tokens)
    if limit is None:
        return used
    limit_tokens = TokenCountResult.exact(
        limit,
        model=tokens.model,
    )
    limit_text = format_token_quantity(limit_tokens)
    return _("{used} / {limit}").format(used=used, limit=limit_text)


__all__ = [
    "ContextTokenBreakdown",
    "TOKEN_UNAVAILABLE_LABEL",
    "format_token_quantity",
    "summarize_token_usage",
]
