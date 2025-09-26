"""Token usage helpers for the agent chat panel."""

from __future__ import annotations

from dataclasses import dataclass

from ...llm.tokenizer import TokenCountResult, combine_token_counts


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


__all__ = ["ContextTokenBreakdown"]
