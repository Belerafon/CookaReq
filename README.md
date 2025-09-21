# CookaReq

CookaReq (Cook a requirement) is a wxPython desktop application for curating structured requirement sets stored as plain JSON files. The repository also ships a command-line interface and a Model Context Protocol (MCP) service so that the same data can be automated from scripts or LLM-powered agents.

## Highlights

- Manage requirements grouped into hierarchical documents with revision tracking and label presets.
- Rich search, filtering and navigation UI with derivation graphs and trace matrix exports.
- Persistent workspace state (window layout, column selections, recently used repositories).
- Command dialog that connects the built-in LocalAgent with MCP tools and an LLM backend.
- FastAPI-based MCP server exposing CRUD and linking operations for external agents.
- Scriptable CLI that mirrors the GUI operations for CI pipelines and bulk maintenance.
- Localisation via `.po` catalogues and configurable colour palettes for label presets.

## Project layout

```
app/            wxPython UI, CLI commands, domain models and integrations
app/agent/      LocalAgent orchestrating LLM + MCP interactions
app/core/       Requirement models, repositories and search utilities
app/mcp/        FastAPI server, client and tool adapters for MCP
app/cli/        Command-line entrypoint and subcommands
requirements/   Example document tree used by tests and demos
docs/           Architecture overview and design notes
tests/          Unit, integration, GUI and smoke suites
build.py        PyInstaller build script for packaging the GUI
```

## Getting started

### Prerequisites

- Python 3.12 (the project targets the system interpreter, virtual environments are recommended).
- Platform packages required by `wxPython`. On Debian/Ubuntu the preinstalled system image already satisfies them.
- Optionally PyInstaller for packaging (install on demand with `python3 -m pip install pyinstaller`).

### Installation

Create and activate a virtual environment, then install the package in editable mode:

```bash
git clone <repository-url>
cd CookaReq
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e ".[dev]"
```

The `[dev]` extra pulls in `pytest`, `pytest-xvfb`, `ruff` and `polib` for development workflows.

### Launching the GUI

Run the desktop client from the repository root:

```bash
python3 -m app.main
```

Choose a requirements directory when prompted. The sample dataset under `requirements/` contains two documents (`SYS`, `HLR`) that demonstrate the expected layout. Window geometry, recent folders, column order and filter selections are persisted via `wx.Config`.

Key interface areas:

1. Document tree with parent/child relationships.
2. Requirement list with configurable columns, search field and advanced filters.
3. Editor panel for creating or modifying the selected item.

Additional dialogs provide label management, derivation graph visualisation, trace matrix export and the LocalAgent command console.

### Command-line quick start

The CLI mirrors GUI operations and is handy for automation:

```bash
python3 -m app.cli doc list requirements
python3 -m app.cli item add requirements SYS --title "New requirement" --statement "…" --labels safety,ui
python3 -m app.cli link requirements SYS-0001 HLR-0002
python3 -m app.cli trace requirements --format html -o trace.html
python3 -m app.cli check --llm   # or --mcp
```

Every command validates input before writing any files. The CLI loads application settings (including LLM/MCP credentials) using the same schema as the GUI.

## Local agent & MCP integration

`app/agent/local_agent.py` combines the LLM client and MCP HTTP tools so that agents can reason over the requirement repository. The GUI exposes it through the **Command** dialog, and the CLI exposes health checks via `python3 -m app.cli check`.

### Configuring API access

- Set the `OPEN_ROUTER` environment variable (it can be placed into a `.env` file) with an API key recognised by the `openai` client.
- Adjust the LLM and MCP parameters from the **Settings** dialog or by editing the settings JSON/TOML file consumed by `app.settings.AppSettings`.
- Token limits and retry policies are validated and normalised during loading.

### MCP endpoints

The background FastAPI application in `app/mcp/server.py` runs in a dedicated thread so the GUI stays responsive. It exposes:

- `GET /health` for readiness checks.
- `POST /mcp` to access MCP tools including `list_requirements`, `get_requirement`, `search_requirements`, `create_requirement`, `patch_requirement`, `delete_requirement` and `link_requirements`.

Tools operate on the directory configured in the settings dialog (`base_path`) and enforce optional bearer-token authentication. Request and response metadata are logged both as human-readable text and structured JSON.

## Requirements repository format

The repository holds requirement documents in nested directories:

```
requirements/
  SYS/
    document.json
    items/
      1.json
  HLR/
    document.json
    items/
      1.json
```

### Document metadata

Each `document.json` contains the human-readable title, an optional parent prefix, label presets (with an `allowFreeform` flag) and arbitrary metadata fields. The directory name is treated as the canonical prefix.

### Requirement items

Each file `items/<id>.json` stores a single requirement with:

- Numeric `id` unique within the document (the GUI renders the RID as `<PREFIX>-<ID>`, zero-padded).
- Descriptive fields such as `title`, `statement`, `type`, `status`, ownership, verification and priority metadata.
- `labels`, `links` and `attachments` with the same schema used in the GUI editor.
- A manual `revision` number that must be incremented by the author; CookaReq persists it as provided.

Search, filtering and derivation logic operate on these JSON structures across the entire hierarchy.

## Localization

Translations live in plain-text `.po` files inside `app/locale/`. The helper `app/i18n.py` wraps :mod:`gettext`: it first asks `gettext.translation` for a catalogue and transparently falls back to parsing the `.po` with `polib` when only text sources are present. The CLI and GUI share the same installer, so switching languages works consistently without generating `.mo` binaries.

## Development workflow

### Running tests

Execute the full suite with:

```bash
pytest -q
```

GUI tests use `pytest-xvfb`, so no display server is needed. Skip them with `pytest -q -m "not gui"` or focus on them via `pytest -q -m gui`. For a quicker check run the smoke group:

```bash
pytest -m smoke -q
```

### Linting

`ruff` is configured via `pyproject.toml`. Run it before committing:

```bash
ruff check app tests
```

### Sample data and docs

- The `requirements/` directory doubles as demo content for the GUI and as fixtures for the automated tests.
- Architectural notes and pointers to key modules are collected in `docs/ARCHITECTURE.md`.

## Building distributables

Install PyInstaller and invoke the build script:

```bash
python3 -m pip install pyinstaller
python3 build.py            # one-folder distribution in dist/CookaReq
python3 build.py --onefile  # optional single-file executable
```

The script bundles the wxPython runtime, JSON schema resources and the application icon.

## License

This project is distributed under the [Apache License 2.0](LICENSE).

© 2025 Maksim Lashkevich & Codex.
