# CookaReq

CookaReq (Cook a requirement) is a wxPython desktop workspace for curating structured requirement sets stored as JSON files.  The repository ships the graphical client, a scriptable command-line interface, a Model Context Protocol (MCP) service, and a lightweight local agent that bridges LLM prompts with requirement operations.

## Highlights

- Manage hierarchical requirement documents with revision tracking, preset label palettes, attachments, and move/copy helpers.
- Import large batches from CSV/TSV/Excel through a column-mapping wizard with previews, automatic ID allocation, and delimiter/sheet controls.
- Rich navigation UI: filterable document tree, configurable list view, Markdown preview, detachable editor and per-requirement history.
- Built-in agent console that streams thoughts, tool calls, confirmations, and reasoning traces; persists transcripts to project-scoped SQLite files, offers timeline/log clipboard exports, and automates batch prompts over selected requirements.
- Structured logging and telemetry (`~/.cookareq/logs` by default) with redaction of sensitive fields and rotating JSON/Text logs for diagnostics.
- FastAPI MCP server launched in-process with token-protected endpoints, trace matrix exports, and configurable log directories.
- Scriptable CLI that mirrors the GUI operations, including create/edit/move/delete flows, trace matrix export, and environment checks.
- Localisation through `.po` catalogues and runtime language switching in the GUI and CLI.

## Repository layout

```
app/
  agent/         LocalAgent orchestration and chat logic
  cli/           Command-line entrypoint and subcommands
  config.py      Persisted UI/LLM/MCP settings shared by GUI and CLI
  core/          Requirement models, repositories, traceability utilities
  i18n.py        Shared translation loader
  llm/           HTTP client, schema validation, and token helpers
  log.py         Structured logging, rotation, and log directory helpers
  mcp/           FastAPI server, MCP client, and tool adapters
  settings.py    Pydantic settings models and normalisation helpers
  telemetry.py   Sanitised telemetry emitters used across the stack
  ui/            wxPython widgets, panels, and controllers
  util/          Cross-cutting helpers (JSON utilities, cancellation, time)
requirements/    Sample requirement repository used by tests and demos
docs/            Architecture notes and work-in-progress design material
tests/           Unit, integration, GUI, smoke, and slow suites organised by markers
tools/           Utility scripts (e.g. wx runner for headless experiments)
build.py         PyInstaller build script producing distributables
```

## Getting started

### Prerequisites

- Python 3.12 (the project targets the system interpreter; use virtual environments for isolation).
- Platform packages required by `wxPython` (the Debian/Ubuntu base image already contains them).
- Optional: PyInstaller for packaging (`python3 -m pip install pyinstaller`).

### Installation

Create and activate a virtual environment, then install CookaReq in editable mode with the development extras:

```bash
git clone <repository-url>
cd CookaReq
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e ".[dev]"
```

The `[dev]` extra installs `pytest`, `pytest-xvfb`, `ruff`, and `polib`. Runtime dependencies (wxPython, FastAPI, MCP client, OpenAI SDK, Pydantic, Markdown, etc.) are declared in `pyproject.toml`.

## Running the GUI client

Launch the desktop application from the repository root:

```bash
python3 -m app.main
```

On first start choose a requirements directory. The bundled dataset under `requirements/` contains three documents (`SYS`, `HLR`, `LLR`) that demonstrate parent/child derivations, cross-links, and label presets. Window geometry, splitter positions, recent folders, log visibility, and agent chat layout are persisted via `ConfigManager` under `~/.config/CookaReq/config.json` (override with `XDG_CONFIG_HOME`).

Key workspace areas:

1. **Document tree** with collapse state, quick filters, and drag-and-drop moves between prefixes.
2. **Requirement list** with configurable columns, saved sorts, Markdown preview, and suspect link indicators.
3. **Editor & history** that exposes attachments, links, revision bumps, and detachable editing windows.
4. **Agent console** that streams LLM messages, tool calls, confirmation prompts, and token counters while logging telemetry events. Conversations persist to `.cookareq/agent_chats.sqlite`, load entries on demand, and surface reasoning/tool timelines with clipboard-friendly plain and log transcripts alongside a batch queue for running the same prompt across multiple requirements.

Additional dialogs provide filter presets, label management, derivation graph visualisation, CSV/Excel import with preview/mapping, trace matrix export, settings, and a log viewer backed by the structured log files.

### Configuration and logs

- UI/MCP/LLM options are validated through `app.settings.AppSettings`. GUI changes persist immediately; the CLI can load overrides via `--settings path/to/settings.json|toml`.
- Set `OPEN_ROUTER` (for example by `source .env`) to provide the OpenRouter API key used by the default LLM client. Other providers can be configured through the Settings dialog or JSON/TOML files.
- Logs live in `~/.cookareq/logs` unless the `COOKAREQ_LOG_DIR` environment variable overrides the path. The MCP server writes its own rotated `server.log`/`server.jsonl` under `<log_dir>/mcp`.
- Agent-specific data lives alongside the requirements directory under `.cookareq/agent_chats.sqlite` (chat history) and `.cookareq/agent_settings.json` (project prompt overrides). When no repository is open the files fall back to the user's home directory.
- LLM settings expose message formats (`openai-chat`, `harmony`, `qwen`), context limits, retries, and optional temperature overrides so both GUI and CLI runs share the same request semantics.

## Command-line interface

All GUI operations are available through `python3 -m app.cli`. The top-level commands are `doc`, `item`, `link`, `trace`, `export`, and `check`. Examples:

```bash
# list documents and inspect repository structure
python3 -m app.cli doc list requirements

# add a requirement using inline arguments
python3 -m app.cli item add requirements SYS \
    --title "New requirement" \
    --statement "Describe behaviour" \
    --labels safety,ui

# move a requirement between documents
python3 -m app.cli item move requirements SYS-0003 --new-prefix LLR

# link requirements and export a traceability matrix
python3 -m app.cli link requirements SYS-0001 HLR-0002
python3 -m app.cli trace requirements --format html -o trace.html

# export selected requirements into Markdown/HTML/PDF with clickable links
python3 -m app.cli export requirements requirements --format markdown -o requirements.md
python3 -m app.cli export requirements requirements --format html -o requirements.html
python3 -m app.cli export requirements requirements --format pdf -o requirements.pdf

# verify LLM and MCP connectivity (uses mocked services by default)
python3 -m app.cli check --llm --mcp
```

Every command validates inputs before mutating files and reuses the same schema as the GUI, including label validation, revision requirements, and MCP authentication checks.

## Local agent and MCP integration

`app.agent.local_agent.LocalAgent` wraps the `LLMClient` and `MCPClient` to execute tool calls in response to LLM prompts. The GUI exposes it via the **Command** dialog/agent panel, while the CLI offers health checks through `python3 -m app.cli check`.

- The default LLM configuration targets `https://openrouter.ai/api/v1` with the `meta-llama/llama-3.3-70b-instruct:free` model to ensure deterministic tool call support. Adjust these fields in *Settings → LLM* or in JSON/TOML overrides when necessary. Real reasoning-capable checks use the free `x-ai/grok-4-fast:free` variant by default; override it via the `OPENROUTER_REASONING_MODEL` environment variable when another model is preferred.
- MCP runs in-process on `127.0.0.1:59362` by default. Enable token checks, change ports, or adjust the base requirements directory from *Settings → MCP*.
- Structured MCP request/response logs (including headers and sanitized payloads) are written to `<log_dir>/mcp/server.log` and `<log_dir>/mcp/server.jsonl` for auditing.

## Requirements repository format

```
requirements/
  SYS/
    document.json
    items/
      1.json
      2.json
  HLR/
    document.json
    items/
      1.json
  LLR/
    document.json
    items/
      1.json
```

Each `document.json` provides the canonical prefix, title, parent prefix, label presets (with `allowFreeform` flags), and arbitrary metadata. Requirement payloads live under `items/<id>.json` and include `title`, `statement`, ownership, verification, revision, attachments, labels, and outgoing links. The GUI/CLI operate strictly on this schema; remove stray files before editing repositories manually.

### Revisions, history, and collaboration

CookaReq deliberately stores requirement documents as plain JSON files and expects teams to manage them with Git (or another VCS). This design provides:

- **History and auditability**: commits, annotations (`git blame`), branches, and pull requests deliver the same traceability as specialised change logs.
- **Baselines**: repository branches/tags serve as baseline snapshots that CI/CD tooling can package automatically.
- **Collaboration**: access policies, reviews, and conflict resolution live on the Git server (GitHub, GitLab, Gitea, etc.), keeping CookaReq a lightweight local client without its own locking server.

The CookaReq GUI and CLI focus on safe filesystem edits and schema validation. After applying changes, follow the standard Git workflow—commit, review, merge—to capture revisions and guarantee quality. If centralised audits or ALM integrations are required, configured Git hooks and external services (for example, generating reports from JSON exports) remain the primary extension points.

## Development workflow

### Running tests

Use the default fast suite (`--suite core`) to cover unit, smoke, and headless integration checks:

```bash
pytest -q
```

GUI suites rely on `pytest-xvfb` and can be executed explicitly:

```bash
pytest -q tests/gui/test_gui.py tests/gui/test_list_panel_gui.py
```

Marker selections are available for quick focus areas, e.g. `pytest -m smoke -q`, `pytest -m gui_full -q`, or `pytest --suite service -q`.

### Real LLM integration tests

Network-bound tests are opt-in to avoid accidental API calls. Provide credentials and flip the suite before running:

```bash
source .env  # exports OPEN_ROUTER
COOKAREQ_RUN_REAL_LLM_TESTS=1 \
pytest --suite real-llm tests/integration/test_llm_openrouter_integration.py::test_openrouter_check_llm -q
```

Without both the environment variable and a valid key the test is skipped automatically.

### Linting and formatting

`ruff` enforces code style, import hygiene, flake8-bugbear safety rules,
flake8-comprehensions normalisation, and flake8-simplify clarity tweaks:

```bash
ruff check app tests
```

## Building distributables

Install PyInstaller if needed and run the build script:

```bash
python3 -m pip install pyinstaller
python3 build.py            # one-folder distribution in dist/CookaReq
python3 build.py --onefile  # optional single-file executable
```

The build bundles the wxPython runtime, JSON schema resources, translations, and application icons.

## License

This project is distributed under the [Apache License 2.0](LICENSE).

© 2025 Maksim Lashkevich & Codex.
