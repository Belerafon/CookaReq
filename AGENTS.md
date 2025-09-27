# AGENTS

This file collects instructions and a short overview of the "CookaReq" application.

## General instructions

- Work on the main branch (no new branches).
- Run `pytest -q`; tests marked `slow` are skipped. The pytest-xvfb plugin is loaded automatically so GUI checks work headlessly.
- Для быстрого прогона конкретного GUI-файла помните, что конфигурация `--suite` в pytest по умолчанию отключает файл, поэтому используйте явный вызов вроде `pytest --suite gui-smoke -q tests/gui/test_list_panel_gui.py`, иначе коллекция отметит весь модуль как «deselected» и не даст обратной связи.
- Quick iterations without the GUI can use `pytest -q -m "not gui"`; to focus solely on the GUI suite run `pytest -q -m gui`.
- GUI tests already run under `pytest-xvfb`. If you disable it for troubleshooting, wrap manual runs with `xvfb-run -a`.
- Use the system Python 3.12.3 for builds and tests. The root `.python-version` file is set to `system`, so `pyenv` switches automatically; run commands through `python3`. The `python` alias is not available. All required packages (including `wxPython`) are already preinstalled in the system installation; verified that `python3 -c "import wx; print(wx.version())"` finishes without errors.
- The OpenRouter key is stored in the `.env` file at the repository root under the `OPEN_ROUTER` variable. Tests and the application read the key from the environment when it is defined.
- The default LLM configuration points to `https://openrouter.ai/api/v1` with the `meta-llama/llama-3.3-70b-instruct:free` model. This free tier was benchmarked to produce consistent MCP tool calls for the "edit the selected requirement" scenario; prefer it unless a task explicitly calls for another backend.
- By default the tests use a mocked LLM and do not call the external API. To run real integration checks, export the credentials (for example `source .env` to load `OPEN_ROUTER`), set `COOKAREQ_RUN_REAL_LLM_TESTS=1` and explicitly switch to the live suite so that marker filtering does not deselect the test:
  ```bash
  source .env
  COOKAREQ_RUN_REAL_LLM_TESTS=1 pytest --suite real-llm tests/integration/test_llm_openrouter_integration.py::test_openrouter_check_llm -q
  ```
  Without the `OPEN_ROUTER` key or the flag these tests are skipped automatically.
- Reflect all meaningful code changes in the architecture file `docs/ARCHITECTURE.md` when they fall within that document's scope.

## GUI testing memo

- The test fixtures start a real `wx.App`, launch `pyvirtualdisplay` when needed, isolate `wx.Config`, and attach markers automatically.
- Most scenarios (`tests/test_gui.py`, `tests/test_list_panel_gui.py`) instantiate real windows (`MainFrame`, `EditorPanel`, `ListPanel`) and assert interactions with actual wx widgets and events.
- Dedicated startup checks (`tests/test_main_runs.py`) run on mocks—they do not replace the full GUI suite.
- Whenever you touch the GUI, run the full GUI test set under a virtual display: `pytest -q tests/test_gui.py tests/test_list_panel_gui.py` (or the entire suite if you are unsure).
- Layout changes in the agent chat transcript have a focused smoke check in `tests/gui/test_agent_chat_panel.py`; run `pytest --suite gui-smoke -q tests/gui/test_agent_chat_panel.py` when iterating on that panel so regressions stay local and quick to debug.
- For ad-hoc GUI experiments outside the pytest fixtures, run scripts through `python tools/run_wx.py your_script.py` (pass additional arguments after `--`). The helper starts a `pyvirtualdisplay` session automatically so `wx` code runs even without a real `$DISPLAY`.

## Short architecture overview

The application follows a layered design:

- **GUI** (`app/ui`) talks to controllers that call services and the `app/core` module.
- **Requirements storage** is represented by JSON documents in the `requirements/` directory and is served by `doc_store`.
- **LLM and MCP** components interact with the storage through `LocalAgent` and `MCPClient`.
- **Builds** are produced by the `build.py` script via PyInstaller.

