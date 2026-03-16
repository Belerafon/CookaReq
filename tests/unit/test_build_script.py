from __future__ import annotations

from pathlib import Path

import build


def test_build_pyinstaller_args_keeps_formula_preview_dependencies() -> None:
    root = Path('/tmp/cookareq')
    args = build._build_pyinstaller_args(
        script=root / 'app' / '__main__.py',
        root=root,
        icon=root / 'app' / 'resources' / 'app.ico',
        hidden_imports=['matplotlib.backends.backend_agg', 'latex2mathml.converter', 'mathml2omml'],
        collect_all_packages=['latex2mathml', 'mathml2omml'],
        collect_data_packages=['matplotlib'],
        excluded_modules=['scipy'],
        onefile=False,
    )

    assert '--collect-data=matplotlib' in args
    assert '--hidden-import=matplotlib.backends.backend_agg' in args
    assert '--collect-all=latex2mathml' in args
    assert '--hidden-import=latex2mathml.converter' in args
    assert '--hidden-import=mathml2omml' in args
    assert '--collect-all=mathml2omml' in args
    assert '--exclude-module=matplotlib' not in args
    assert '--exclude-module=numpy' not in args


def test_build_pyinstaller_args_onefile_switch_replaces_onedir() -> None:
    root = Path('/tmp/cookareq')
    args = build._build_pyinstaller_args(
        script=root / 'app' / '__main__.py',
        root=root,
        icon=root / 'app' / 'resources' / 'app.ico',
        hidden_imports=[],
        collect_all_packages=[],
        collect_data_packages=[],
        excluded_modules=[],
        onefile=True,
    )

    assert '--onefile' in args
    assert '--onedir' not in args


def test_ensure_supported_python_rejects_non_312(monkeypatch) -> None:
    class _V:
        major = 3
        minor = 13
        micro = 1

    monkeypatch.setattr(build.sys, 'version_info', _V())

    import pytest

    with pytest.raises(SystemExit, match=r'requires Python 3\.12\.x'):
        build.ensure_supported_python()
