"""Shared constants for LLM configuration limits and defaults."""

DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
"""OpenRouter-compatible endpoint used when no override is provided."""

DEFAULT_LLM_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
"""Default free model tuned for reliable tool use on OpenRouter."""

DEFAULT_MAX_CONTEXT_TOKENS = 131072
"""Maximum prompt size sent to the LLM when the user does not override it."""

MIN_MAX_CONTEXT_TOKENS = 2000
"""Lower bound for the prompt context size accepted from configuration."""

DEFAULT_LLM_TEMPERATURE = 0.7
"""Model sampling temperature used when the user enables overrides."""
