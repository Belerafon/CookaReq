from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional


class SecretEnvValue:
    """Container for secrets that hides their value in repr/str output.

    Tests can safely pass the secret further through the object, calling
    :meth:`get_secret_value` when the actual string is required.  Any implicit
    conversion to ``str`` (for example, when interpolated in logs) will be
    masked to avoid accidental disclosure of sensitive data during debugging
    or in CI logs.
    """

    __slots__ = ("_name", "__value")

    def __init__(self, name: str, value: str) -> None:
        if not name:
            raise ValueError("SecretEnvValue requires a non-empty variable name")
        if value is None or value == "":
            raise ValueError("SecretEnvValue requires a non-empty value")
        self._name = name
        self.__value = value

    @property
    def name(self) -> str:
        return self._name

    def get_secret_value(self) -> str:
        return self.__value

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return True

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<SecretEnvValue {self._name}=***>"

    __str__ = __repr__

    def __format__(self, format_spec: str) -> str:  # pragma: no cover - trivial
        return str(self)


def load_secret_from_env(
    variable_name: str,
    *,
    search_from: Path | str | None = None,
    env_file_name: str = ".env",
) -> Optional[SecretEnvValue]:
    """Load a secret from the environment or the nearest ``.env`` file.

    Parameters
    ----------
    variable_name:
        Name of the environment variable to look up.
    search_from:
        Starting path for searching ``.env`` files in parent directories.
        When ``None`` (default) the current working directory is used.
    env_file_name:
        Allows overriding the name of the dotenv file during tests.
    """

    value = os.getenv(variable_name)
    if value:
        return SecretEnvValue(variable_name, value)

    search_root = _normalise_search_root(search_from)
    for env_path in _iter_env_paths(search_root, env_file_name):
        value = _extract_from_env_file(env_path, variable_name)
        if value:
            return SecretEnvValue(variable_name, value)
    return None


def _normalise_search_root(search_from: Path | str | None) -> Path:
    if search_from is None:
        return Path.cwd()
    path = Path(search_from)
    return path if path.is_dir() else path.parent


def _iter_env_paths(root: Path, env_file_name: str) -> Iterable[Path]:
    for directory in (root, *root.parents):
        env_path = directory / env_file_name
        if env_path.is_file():
            yield env_path


def _extract_from_env_file(env_path: Path, variable_name: str) -> Optional[str]:
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        if name.strip() != variable_name:
            continue
        raw_value = raw_value.strip()
        if not raw_value:
            return None
        is_double_quoted = raw_value.startswith("\"") and raw_value.endswith("\"")
        is_single_quoted = raw_value.startswith("'") and raw_value.endswith("'")
        if is_double_quoted or is_single_quoted:
            value = raw_value[1:-1]
        else:
            value = raw_value.split("#", 1)[0].rstrip()
        return value
    return None
