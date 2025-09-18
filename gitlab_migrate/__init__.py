"""Compatibility wrappers for the external GitLab migration tooling."""

from tools import gitlab_migrate as _gitlab_migrate
from tools.gitlab_migrate import *  # noqa: F401,F403 - re-export for legacy imports

__all__ = _gitlab_migrate.__all__
