"""Shared constants for LLM configuration limits."""

DEFAULT_MAX_OUTPUT_TOKENS = 5000
"""Fallback response length cap when the user does not configure one."""

MIN_MAX_OUTPUT_TOKENS = 1000
"""Lowest value accepted from the user for LLM responses."""

DEFAULT_MAX_CONTEXT_TOKENS = 12000
"""Maximum prompt size sent to the LLM when the user does not override it."""

MIN_MAX_CONTEXT_TOKENS = 2000
"""Lower bound for the prompt context size accepted from configuration."""
