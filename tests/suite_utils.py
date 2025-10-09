from __future__ import annotations

import os
from pathlib import Path

from tests.env_utils import load_secret_from_env

_REAL_LLM_FLAG = "COOKAREQ_RUN_REAL_LLM_TESTS"
_OPEN_ROUTER_VAR = "OPEN_ROUTER"


def auto_opt_in_real_llm_suite(
    *,
    env_flag: str = _REAL_LLM_FLAG,
    secret_var: str = _OPEN_ROUTER_VAR,
    search_from: Path | str | None = None,
) -> bool:
    """Ensure the real-LLM flag is enabled when credentials are available.

    The helper mirrors the behaviour of ``require_real_llm_tests_flag`` but is
    meant to be invoked from the pytest configuration stage.  When the flag is
    not set yet, the function attempts to discover the ``secret_var`` value via
    :func:`tests.env_utils.load_secret_from_env`.  If the secret is found, the
    flag is exported with the ``"1"`` value so tests relying on
    ``require_real_llm_tests_flag`` proceed without extra manual steps.

    Returns ``True`` when the flag is present after the call (either because it
    was already defined or because the helper managed to auto-enable it).
    ``False`` indicates that the flag is still absent, typically due to missing
    credentials.
    """

    if os.getenv(env_flag):
        return True

    secret = load_secret_from_env(secret_var, search_from=search_from)
    if secret is None:
        return False

    os.environ[env_flag] = "1"
    return True
