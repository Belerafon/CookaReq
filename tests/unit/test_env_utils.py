from __future__ import annotations

import pytest

from tests.env_utils import SecretEnvValue, load_secret_from_env


def test_loads_from_environment_overrides_dotenv(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OPEN_ROUTER=from-file\n", encoding="utf-8")
    monkeypatch.setenv("OPEN_ROUTER", "from-env")

    secret = load_secret_from_env("OPEN_ROUTER", search_from=tmp_path)

    assert isinstance(secret, SecretEnvValue)
    assert secret.get_secret_value() == "from-env"


def test_loads_from_nearest_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("OPEN_ROUTER", raising=False)
    nested = tmp_path / "nested" / "child"
    nested.mkdir(parents=True)
    env_path = tmp_path / ".env"
    env_path.write_text("OPEN_ROUTER=from-dotenv\n", encoding="utf-8")

    secret = load_secret_from_env("OPEN_ROUTER", search_from=nested)

    assert secret is not None
    assert secret.get_secret_value() == "from-dotenv"


@pytest.mark.parametrize(
    "line,expected",
    [
        ("OPEN_ROUTER=plain", "plain"),
        ("OPEN_ROUTER='single-quoted'", "single-quoted"),
        ("OPEN_ROUTER=\"double-quoted\"", "double-quoted"),
        ("export OPEN_ROUTER=exported", "exported"),
        ("OPEN_ROUTER=value # comment", "value"),
        ("OPEN_ROUTER=\"quoted # comment\"", "quoted # comment"),
    ],
)
def test_parses_supported_line_formats(monkeypatch, tmp_path, line, expected):
    monkeypatch.delenv("OPEN_ROUTER", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(f"{line}\n", encoding="utf-8")

    secret = load_secret_from_env("OPEN_ROUTER", search_from=tmp_path)

    assert secret is not None
    assert secret.get_secret_value() == expected


def test_secret_repr_masks_value(monkeypatch, tmp_path):
    monkeypatch.setenv("OPEN_ROUTER", "top-secret")

    secret = load_secret_from_env("OPEN_ROUTER", search_from=tmp_path)

    assert secret is not None
    assert "top-secret" not in str(secret)
    assert secret.get_secret_value() == "top-secret"
