from __future__ import annotations

from pathlib import Path

import build


def test_build_pyinstaller_args_keeps_formula_preview_dependencies() -> None:
    root = Path('/tmp/cookareq')
    args = build._build_pyinstaller_args(
        script=root / 'app' / '__main__.py',
        root=root,
        icon=root / 'app' / 'resources' / 'app.ico',
        hidden_imports=['matplotlib.backends.backend_agg', 'latex2mathml.converter'],
        collect_packages=['matplotlib', 'latex2mathml'],
        excluded_modules=['scipy'],
        onefile=False,
    )

    assert '--collect-all=matplotlib' in args
    assert '--hidden-import=matplotlib.backends.backend_agg' in args
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
