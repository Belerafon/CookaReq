from __future__ import annotations

from pathlib import Path

import pytest

import build


def test_build_pyinstaller_args_keeps_formula_preview_dependencies() -> None:
    root = Path('/tmp/cookareq')
    args = build._build_pyinstaller_args(
        script=root / 'app' / '__main__.py',
        root=root,
        icon=root / 'app' / 'resources' / 'app.ico',
        hidden_imports=['matplotlib.backends.backend_agg', 'latex2mathml.converter', 'numpy.core._multiarray_umath'],
        collect_packages=['numpy', 'matplotlib', 'latex2mathml'],
        excluded_modules=['scipy'],
        onefile=False,
    )

    assert '--collect-all=matplotlib' in args
    assert '--hidden-import=matplotlib.backends.backend_agg' in args
    assert '--hidden-import=numpy.core._multiarray_umath' in args
    assert '--collect-all=numpy' in args
    assert '--collect-all=latex2mathml' in args
    assert '--hidden-import=latex2mathml.converter' in args
    assert '--exclude-module=matplotlib' not in args
    assert '--exclude-module=numpy' not in args


def test_build_pyinstaller_args_onefile_switch_replaces_onedir() -> None:
    root = Path('/tmp/cookareq')
    args = build._build_pyinstaller_args(
        script=root / 'app' / '__main__.py',
        root=root,
        icon=root / 'app' / 'resources' / 'app.ico',
        hidden_imports=[],
        collect_packages=[],
        excluded_modules=[],
        onefile=True,
    )

    assert '--onefile' in args
    assert '--onedir' not in args


def test_validate_build_environment_reports_missing_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken_import(name: str):
        raise ImportError(name)

    monkeypatch.setattr(build.importlib, "import_module", _broken_import)

    with pytest.raises(RuntimeError) as excinfo:
        build._validate_build_environment(("matplotlib", "latex2mathml.converter"))

    message = str(excinfo.value)
    assert "matplotlib" in message
    assert "latex2mathml.converter" in message
    assert "requirements-build.txt" in message


def test_validate_build_environment_accepts_available_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build.importlib, "import_module", lambda _name: object())

    build._validate_build_environment(("numpy", "matplotlib"))
