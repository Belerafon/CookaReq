# CookaReq

CookaReq ("Cook a requirement") is a wxPython desktop application for curating structured requirement repositories. The project bundles a rich graphical interface, a command-line utility, and an MCP server so that the same JSON-backed store can be managed manually or by external agents.

## Highlights

- **Multi-pane desktop UI** that keeps the document tree, requirement table, editor, agent chat, and log console in sync. Columns, splitter positions, window geometry, and recent folders persist through `wx.Config` so the workspace reopens exactly as it was left.
- **Deep requirement editing** with cloning, derivation support, attachments, suspect link tracking, and document-level label presets inherited down the hierarchy.
- **LocalAgent integration** that combines the OpenAI-compatible LLM client with the HTTP MCP client. The chat panel and CLI share the same orchestration layer, telemetry logging, and JSON error surface.
- **Command-line tooling** for headless automation: manage documents and items, move requirements between folders, export trace matrices, and verify MCP/LLM connectivity from scripts or CI.
- **FastAPI-based MCP server** that exposes CRUD and linking operations with optional bearer-token authentication and dual text/JSONL request logs for auditing.
- **Internationalisation-first workflow**: translations live as `.po` files and missing strings are collected automatically for later review.

## Project layout

- `app/` — application source code split into GUI, core domain model, CLI, LLM, MCP, and helper packages.
- `requirements/` — sample requirement repository used by the UI, tests, and MCP tools.
- `docs/ARCHITECTURE.md` — high-level orientation guide for the code base.
- `tests/` — unit, integration, GUI, smoke, and slow test suites (slow tests are skipped by default).
- `tools/` — maintenance scripts for the JSON repositories.

## Getting started

### Prerequisites

- Python 3.12 with wxPython support.
- Graphviz installed and on `PATH` if you want to render derivation graphs.
- (Optional) An OpenAI-compatible endpoint; real LLM calls expect the key in the `OPEN_ROUTER` environment variable or in a `.env` file at the project root.

### Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # runtime dependencies
pip install -e .[dev]                     # optional: linting & tests
```

### Sample data

The repository ships with an example hierarchy under `requirements/`. Each top-level folder (e.g. `SYS`, `HLR`, `LLR`) contains a `document.json` descriptor and an `items/` directory with numbered requirement files.

## Running the GUI

Launch the desktop client with:

```bash
python3 -m app.main
```

The main window splits into several panes:

1. **Hierarchy** — the document tree with create/rename/delete actions. Parent/child relationships control inherited label presets and free-form label permissions.
2. **Requirements** — a sortable table with configurable columns, saved filters, derived-count indicators, and context menu actions for cloning, deriving, or bulk deleting entries.
3. **Editor** — a form driven by `editor_fields.json` that validates input, manages attachments, and enforces label presets.
4. **Agent chat** — an optional pane that talks to `LocalAgent` for assisted editing.
5. **Log console** — a toggleable text view that mirrors the structured telemetry stream.

The **Navigation** menu stores recent folders, switches optional panes on and off, opens the derivation graph/trace matrix windows, and exposes the command dialog for issuing agent queries. GUI state (window geometry, splitter positions, active columns, language preference) is captured via `ConfigManager` so that the layout is restored on next launch.

## Command-line interface

Run `python3 -m app.cli --help` to inspect available subcommands. The CLI shares the same core layer as the GUI and supports JSON/TOML settings via `--settings`.

| Command | Purpose |
| --- | --- |
| `doc create/list/delete` | Manage document folders and inspect planned deletions before committing changes. |
| `item add/edit/move/delete` | Create requirements from scratch or JSON templates, edit in place, relocate between documents with revision checks, and prune items safely. |
| `link` | Attach parent RIDs to a requirement while validating ancestry and collision rules. |
| `trace` | Export the derived-from matrix in plain text, CSV, or HTML formats. |
| `check` | Run LLM and/or MCP health checks using the current settings bundle. |

All destructive commands prompt for confirmation unless `auto_confirm` is active (as in the CLI). Validation mirrors the GUI: label presets are enforced, revisions are compared, and malformed JSON raises human-readable errors.

## LocalAgent, LLM, and MCP integration

The LocalAgent binds together `LLMClient` and `MCPClient`, providing synchronous and asynchronous adapters for command parsing and tool execution. Telemetry redacts sensitive keys before logging and measures payload size/duration for each request.

- Configure connection details in the **Settings** dialog or by supplying a JSON/TOML file to the CLI. Token limits are normalised and validation errors are surfaced via `pydantic` models.
- The MCP server runs inside the application process. When `auto_start` is enabled, the GUI launches the server on start-up and keeps it in sync with configuration changes. The `/health` endpoint powers status checks while requests are written both as human-readable logs and JSONL telemetry under the configured base path.
- Real LLM requests are optional; tests and the CLI default to a mock backend unless you export `OPEN_ROUTER` and opt into the integration scenarios (set `COOKAREQ_RUN_REAL_LLM_TESTS=1`).

## Requirement repository structure

```
requirements/
  SYS/
    document.json
    items/
      001.json
      002.json
  HLR/
    document.json
    items/
      001.json
```

### Document configuration (`document.json`)

- `title` — human-readable name shown in the tree.
- `digits` — zero-padding width for item identifiers.
- `parent` — optional prefix of the parent document.
- `labels` — label policy with `allowFreeform` and a list of `{ "key", "title", "color" }` definitions.
- `attributes` — arbitrary metadata for future extensions.

The folder name is treated as the canonical prefix; mismatches are rejected to keep identifiers stable.

### Requirement files (`items/<ID>.json`)

Each requirement stores:

- Scalar metadata: `id`, `title`, `statement`, `type`, `status`, `owner`, `priority`, `source`, `verification`, `acceptance`, `conditions`, `rationale`, `assumptions`, `modified_at`, `approved_at`, `notes`.
- Lists: `labels` (validated against presets unless free-form is enabled), `attachments` (`{ "path", "note" }`), and `links`.
- Revision tracking via `revision` (must be a positive integer; callers provide the expected value when editing or moving items).
- Link objects may include `{ "rid", "fingerprint", "suspect" }` so downstream tools can highlight stale derivations.

Runtime metadata such as `doc_prefix`, `rid`, and derived counts are generated on the fly by the application layer and are not persisted to disk.

## Localization and configuration

Translations live under `app/locale/`. On exit the application appends missing strings to `missing.po`, making it easy to iterate on localisation without recompiling catalogs.

User preferences (columns, window geometry, language, LLM credentials, recent folders) are stored via `ConfigManager` in the platform-specific `wx.Config` location. The CLI reuses the same store when invoked with the default configuration name, or it can read explicit settings files through `AppSettings`.

## Logging and telemetry

`configure_logging()` installs a stream logger for console diagnostics, while the GUI mirrors entries into the log console widget. Structured events go through `log_event()` which redacts sensitive keys and records payload sizes/durations. When the MCP server is active, every request is additionally written to `server.log` and `server.jsonl` under the configured base path.

## Testing

Run the full suite with:

```bash
pytest -q
```

For a quicker smoke test:

```bash
pytest -m smoke -q
```

GUI tests run headless through `pytest-xvfb`. Real LLM checks remain skipped unless `COOKAREQ_RUN_REAL_LLM_TESTS=1` and a valid `OPEN_ROUTER` key are present.

## Building distributables

Use the PyInstaller helper to create a standalone build:

```bash
python3 build.py             # produces dist/CookaReq/
python3 build.py --onefile   # optional single binary
```

The script bundles the GUI entry point, icons, and required binary data for wxPython and `jsonschema`. Hidden imports are declared explicitly so runtime discovery succeeds.

## License

CookaReq is distributed under the [Apache License 2.0](LICENSE).
