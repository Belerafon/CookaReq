"""Helpers for counting tokens for configured language models."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from typing import Iterable, Mapping

__all__ = [
    "TokenCountResult",
    "combine_token_counts",
    "count_text_tokens",
]


@dataclass(frozen=True)
class TokenCountResult:
    """Outcome of a tokenisation attempt."""

    tokens: int | None
    approximate: bool = False
    model: str | None = None
    reason: str | None = None

    @classmethod
    def exact(
        cls,
        tokens: int,
        *,
        model: str | None = None,
        reason: str | None = None,
    ) -> "TokenCountResult":
        """Return a successful, precise token count."""

        return cls(tokens=max(tokens, 0), approximate=False, model=model, reason=reason)

    @classmethod
    def approximate_result(
        cls,
        tokens: int,
        *,
        model: str | None = None,
        reason: str | None = None,
    ) -> "TokenCountResult":
        """Return an approximate token count."""

        return cls(tokens=max(tokens, 0), approximate=True, model=model, reason=reason)

    @classmethod
    def unavailable(
        cls,
        *,
        model: str | None = None,
        reason: str | None = None,
    ) -> "TokenCountResult":
        """Return a result indicating that tokenisation failed."""

        return cls(tokens=None, approximate=False, model=model, reason=reason)

    def to_dict(self) -> dict[str, object]:
        """Serialise the result for JSON storage."""

        payload: dict[str, object] = {}
        if self.tokens is not None:
            payload["tokens"] = int(self.tokens)
        payload["approximate"] = bool(self.approximate)
        if self.model:
            payload["model"] = self.model
        if self.reason:
            payload["reason"] = self.reason
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "TokenCountResult":
        """Create :class:`TokenCountResult` from a mapping."""

        tokens_value = payload.get("tokens")
        tokens: int | None
        if isinstance(tokens_value, bool):
            tokens = 1 if tokens_value else 0
        elif isinstance(tokens_value, (int, float)):
            tokens = int(tokens_value)
        else:
            try:
                tokens = int(str(tokens_value)) if tokens_value is not None else None
            except (TypeError, ValueError):  # pragma: no cover - defensive
                tokens = None
        approximate = bool(payload.get("approximate", False))
        model = payload.get("model")
        model_text = model if isinstance(model, str) and model.strip() else None
        reason = payload.get("reason")
        reason_text = reason if isinstance(reason, str) and reason.strip() else None
        if tokens is None:
            return cls.unavailable(model=model_text, reason=reason_text)
        if approximate:
            return cls.approximate_result(tokens, model=model_text, reason=reason_text)
        return cls.exact(tokens, model=model_text, reason=reason_text)


_TIKTOKEN_CACHE: object | None = None


def _load_tiktoken() -> object | None:
    """Return the cached :mod:`tiktoken` module when available."""

    global _TIKTOKEN_CACHE
    if _TIKTOKEN_CACHE is not None:
        return None if _TIKTOKEN_CACHE is False else _TIKTOKEN_CACHE
    if "tiktoken" in sys.modules:
        module = sys.modules["tiktoken"]
        _TIKTOKEN_CACHE = module
        return module
    spec = importlib.util.find_spec("tiktoken")
    if spec is None:
        _TIKTOKEN_CACHE = False
        return None
    module = importlib.import_module("tiktoken")
    _TIKTOKEN_CACHE = module
    return module


def _whitespace_count(text: str) -> int:
    """Return a rough token estimate by splitting on whitespace."""

    stripped = text.strip()
    if not stripped:
        return 0
    return len(stripped.split())


def count_text_tokens(text: object, *, model: str | None = None) -> TokenCountResult:
    """Return token statistics for *text* using the provided *model*.

    When :mod:`tiktoken` is available the helper attempts to use the model-
    specific encoding.  Unknown models fall back to ``cl100k_base``.  If neither
    strategy works, a simple whitespace-based approximation is returned.
    """

    try:
        text_value = "" if text is None else str(text)
    except Exception as exc:  # pragma: no cover - defensive
        return TokenCountResult.unavailable(model=model, reason=f"coerce_failed: {exc}")

    if not text_value:
        return TokenCountResult.exact(0, model=model)

    module = _load_tiktoken()
    encoding = None
    if module is not None:
        get_encoding = getattr(module, "encoding_for_model", None)
        if callable(get_encoding) and model:
            try:
                encoding = get_encoding(model)
            except KeyError:
                encoding = None
        if encoding is None:
            fallback = getattr(module, "get_encoding", None)
            if callable(fallback):
                try:
                    encoding = fallback("cl100k_base")
                except KeyError:  # pragma: no cover - defensive
                    encoding = None
        if encoding is not None:
            try:
                tokens = len(encoding.encode(text_value, disallowed_special=()))
            except Exception as exc:  # pragma: no cover - defensive
                estimate = _whitespace_count(text_value)
                return TokenCountResult.approximate_result(
                    estimate,
                    model=model,
                    reason=f"tokenize_failed: {exc}",
                )
            if model and getattr(encoding, "name", None) == model:
                return TokenCountResult.exact(tokens, model=model)
            return TokenCountResult.approximate_result(
                tokens,
                model=model,
                reason="model_approximation",
            )

    estimate = _whitespace_count(text_value)
    return TokenCountResult.approximate_result(
        estimate,
        model=model,
        reason="fallback_whitespace",
    )


def combine_token_counts(results: Iterable[TokenCountResult | None]) -> TokenCountResult:
    """Aggregate multiple token counts into a single result."""

    total = 0
    have_value = False
    approximate = False
    reasons: list[str] = []
    model: str | None = None
    tokens_unknown = False
    for result in results:
        if result is None:
            continue
        if result.tokens is None:
            tokens_unknown = True
        else:
            total += result.tokens
            have_value = True
        approximate = approximate or result.approximate
        if result.reason:
            reasons.append(result.reason)
        if model is None:
            model = result.model
        elif result.model != model:
            model = None
    if tokens_unknown:
        return TokenCountResult.unavailable(
            model=model,
            reason="; ".join(reasons) if reasons else None,
        )
    if not have_value:
        return TokenCountResult.exact(0, model=model)
    return TokenCountResult(
        tokens=total,
        approximate=approximate,
        model=model,
        reason="; ".join(reasons) if reasons else None,
    )
