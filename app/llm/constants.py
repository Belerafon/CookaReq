"""Shared constants for LLM configuration limits."""

DEFAULT_MAX_CONTEXT_TOKENS = 12000
"""Maximum prompt size sent to the LLM when the user does not override it."""

MIN_MAX_CONTEXT_TOKENS = 2000
"""Lower bound for the prompt context size accepted from configuration."""
