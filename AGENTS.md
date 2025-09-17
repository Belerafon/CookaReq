# AGENTS

This file collects instructions and a short overview of the "CookaReq" application.

## General instructions

- Work on the main branch (no new branches).
- Run `pytest -q`; tests marked `slow` are skipped.
- When re-enabling tests that rely on `wx`, run them under a virtual display (the `pytest-xvfb` plugin or an `xvfb-run -a` wrapper).
- Use the system Python 3.12.3 for builds and tests. The root `.python-version` file is set to `system`, so `pyenv` switches automatically; run commands through `python3`. The `python` alias is not available. All required packages (including `wxPython`) are already preinstalled in the system installation; verified that `python3 -c "import wx; print(wx.version())"` finishes without errors.
- The OpenRouter key is stored in the `.env` file at the repository root under the `OPEN_ROUTER` variable. Tests and the application read the key from the environment when it is defined.
- By default the tests use a mocked LLM and do not call the external API. To run real integration checks, set `COOKAREQ_RUN_REAL_LLM_TESTS=1` and execute tests with the `real_llm` marker, for example:
  `COOKAREQ_RUN_REAL_LLM_TESTS=1 pytest tests/test_llm_openrouter_integration.py::test_openrouter_check_llm -q`. Without the `OPEN_ROUTER` key or the flag these tests are skipped.
- Reflect all meaningful code changes in the architecture file `docs/ARCHITECTURE.md` when they fall within that document's scope.

## GUI testing memo

- The test fixtures start a real `wx.App`, launch `pyvirtualdisplay` when needed, isolate `wx.Config`, and attach markers automatically.
- Most scenarios (`tests/test_gui.py`, `tests/test_list_panel_gui.py`) instantiate real windows (`MainFrame`, `EditorPanel`, `ListPanel`) and assert interactions with actual wx widgets and events.
- Dedicated startup checks (`tests/test_main_runs.py`) run on mocks—they do not replace the full GUI suite.
- Whenever you touch the GUI, run the full GUI test set under a virtual display: `pytest -q tests/test_gui.py tests/test_list_panel_gui.py` (or the entire suite if you are unsure).

## Short architecture overview

The application follows a layered design:

- **GUI** (`app/ui`) talks to controllers that call services and the `app/core` module.
- **Requirements storage** is represented by JSON documents in the `requirements/` directory and is served by `doc_store`.
- **LLM and MCP** components interact with the storage through `LocalAgent` and `MCPClient`.
- **Builds** are produced by the `build.py` script via PyInstaller.

