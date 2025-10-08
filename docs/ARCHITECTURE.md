# CookaReq Architecture Overview

This guide is meant to orient new contributors. It captures the shape of the
codebase, the dominant data flows, how the agent and MCP layers work together,
and which tests protect each area. Use it as a map before you dive into a task
so you know which modules are involved and which regressions to guard against.

## Top-level structure

| Path | Description |
| --- | --- |
| `app/main.py`, `app/application.py` | GUI entry point and the dependency container (`ApplicationContext`). |
| `app/core/` | Persistent requirement store, core models, search helpers, trace matrix generation, import/export code. |
| `app/services/` | High-level facades on top of the core, including document caching, user document ingestion and configuration. |
| `app/agent/` | The local agent that orchestrates LLM calls, MCP tool executions and confirmation flows. |
| `app/llm/` | OpenRouter client, prompt builders, validators, tokenizer helpers and context assembly. |
| `app/mcp/` | HTTP server, controller and tool implementations for machine-checkable requirements edits. |
| `app/ui/` | wxPython UI (frames, panels, controllers, models, dialogs). |
| `app/util/`, `app/log.py`, `app/telemetry.py` | Cross-cutting utilities: cancellation, JSON helpers, timing, logging and telemetry. |
| `requirements/` | Bundled sample requirements packs (`DEMO/…`). |
| `tests/` | End-to-end, GUI, services and core suites (see `tests/README.md`). |
| `tools/` | Development helpers such as `run_wx.py` for running wx scripts under a virtual display. |

## Core domain: requirements and traceability

* **On-disk layout** — each document lives under `requirements/<PREFIX>/`.
  * `document.json` stores metadata (title, parent, labels).
  * `items/<ID>.json` keeps individual requirement payloads.
  * `agent_chats.zip` retains previous agent transcripts for that document.
* **Document store** — `app/core/document_store/` exposes CRUD helpers for
  documents, items, relationship links and label collections. It keeps ID
  counters, validates JSON payloads and hides filesystem concerns from callers.
* **Domain models** — `app/core/model.py` defines `Requirement` and supporting
  enums (status, priority, link types). Any schema change must stay in sync with
  the JSON representation and migrations for existing files.
* **Search and filtering** — `app/core/search.py` provides predicates used by
  the wx models in `app/ui/requirement_model.py` to filter by text, labels and
  status. Sorting also happens in these layers.
* **Traceability** — `app/core/trace_matrix.py` builds matrices that map
  requirements to external artefacts. The GUI reuses cached document data to
  avoid expensive reloads.
* **Import/export** — `requirement_import.py` and `requirement_export.py`
  convert between external formats and the `Requirement` dataclass while
  delegating all persistence to the document store.

## Application services and configuration context

* **`RequirementsService`** — wraps the document store with caching, consistent
  path resolution and domain-specific errors (`DocumentNotFoundError`,
  `ValidationError`). Both the GUI and automation flows consume this service
  instead of calling the core directly.
* **`UserDocumentsService`** — indexes external documentation for the agent.
  It enforces size limits, token budgets and serialises directory snapshots so
  that LLM prompts only include manageable chunks.
* **`ApplicationContext`** — defined in `app/application.py`. It wires up
  factories for configuration management, requirement models, services, the
  local agent and the MCP controller. Both GUI and CLI entry points rely on the
  context for consistent wiring.
* **`ConfigManager`** — lives in `app/config.py` and persists UI state and
  integration settings (`llm`, `mcp`, panels, splitter positions) in
  `~/.config/CookaReq/config.json`. It bridges Pydantic settings (`app/settings.py`)
  and runtime wx widgets.

## Agent, LLM and MCP layers

* **Local agent (`app/agent/local_agent.py`)** — orchestrates conversations by
  pairing an `LLMClient` with an `MCPClient`. It builds prompts, enforces step
  limits, handles retry windows, manages confirmation hooks and keeps a running
  transcript of decisions.
* **LLM package (`app/llm/`)** — `client.py` wraps OpenRouter, `request_builder.py`
  assembles prompt payloads, `validation.py` and `response_parser.py` normalise
  model outputs, `context.py` selects relevant requirements and user documents,
  and `tokenizer.py` estimates prompt size. The package is designed so new
  providers can be introduced behind the same `LLMClient` API.
* **MCP server (`app/mcp/`)** — `server.py` exposes HTTP endpoints for tool
  execution, `controller.py` launches and monitors the server from the GUI,
  `client.py` issues requests with idempotent confirmation tokens, while
  `tools_read.py` and `tools_write.py` implement read/write primitives against
  the document store. `events.py` broadcasts completion notifications that let
  the UI refresh without reloading the entire document tree.

## Graphical interface

* **Entry point** — `app/main.py` initialises locale settings, builds the
  `ApplicationContext.for_gui()` instance, then instantiates `MainFrame`.
* **Panels and views**
  * `document_tree.py` and `list_panel.py` show documents and filtered lists of
    requirements.
  * `editor_panel.py` manages requirement editing and metadata updates.
  * `agent_chat_panel/` displays the running agent transcript, batching controls
    and confirmation toggles. Long-running commands execute through
    `ThreadedAgentCommandExecutor` (a single-worker `ThreadPoolExecutor`).
    `tool_result_state.py` keeps the merge logic for streamed tool results
    linear and testable (timestamps, status updates, raw tool arguments).
  * `trace_matrix.py` and `derivation_graph.py` visualise relationships.
* **Controllers** — under `app/ui/controllers/`, they translate wx events into
  service calls (`DocumentsController`, `MCPController`, etc.). Controllers take
  care of ID uniqueness, validation and model updates before hitting the store.
* **Models** — `RequirementModel` caches the active requirement set in memory
  and exposes filtered views to the list panel, keeping UI updates fast.
* **Dialogs and helpers** — confirmation flows, error dialogs and settings live
  in `app/confirm.py`, `app/ui/error_dialog.py`, `app/ui/settings_dialog.py` and
  related modules.

## Cross-cutting infrastructure

* **Settings** — `app/settings.py` defines `AppSettings` with grouped sections
  (`llm`, `mcp`, `ui`). TOML/JSON aliases map onto friendly names like
  `api_base`.
* **Logging and telemetry** — `app/log.py` configures rotating logs. Significant
  events are funnelled through `app/telemetry.log_event`, which masks sensitive
  tokens before persistence.
* **Utilities** — `app/util/` packages cancellation primitives, safe JSON
  dumping, time measurement and other helpers used by multiple layers.
* **Build tooling** — `build.py` assembles distributable bundles with
  PyInstaller, reusing resources under `app/resources/` and localisation assets
  from `app/locale/`.

## Data flows

### Application startup
1. `app/main.main()` configures logging and creates an
   `ApplicationContext.for_gui()` instance.
2. The context loads configuration via `ConfigManager`, restores open documents
   and prepares service singletons.
3. `MainFrame` wires controllers to wx events and registers listeners for MCP
   events and agent updates.

### Document loading and presentation
1. `DocumentsController.load_documents()` calls
   `RequirementsService.load_documents(refresh=True)`, which delegates to the
   document store.
2. Selecting a document triggers `RequirementsService.load_requirements()`,
   which returns `Requirement` instances for the wx model.
3. `RequirementModel.set_requirements()` holds the collection in memory and
   provides filtered projections to the list panel.

### Editing and persistence
1. The UI builds a `Requirement` from the editor panel and passes it to
   `DocumentsController.save_requirement()`.
2. The controller validates uniqueness through `RequirementsService.list_item_ids()`
   and `document_store.rid_for()`.
3. `RequirementsService.save_requirement_payload()` serialises the change via
   `document_store.save_item()` and updates the in-memory model through
   `RequirementModel.update()`.
4. Document creation and deletion route through `RequirementsService` to keep
   the cache consistent with on-disk state.

### Agent and MCP interaction
1. `AgentChatPanel` gathers the current context and invokes
   `LocalAgent.respond_async()` through `ThreadedAgentCommandExecutor`.
2. The agent assembles prompts with `app/llm/context.py` and sends them via the
   LLM client. Planned tool invocations are validated before execution.
3. `MCPClient.call_tool_async()` issues HTTP requests to the local MCP server
   (`app/mcp/server.py`).
4. On success, `events.notify_tool_success` informs subscribers (UI, telemetry)
   so the requirement model refreshes without reloading everything from disk.

## Persistence and operational environment

* Sample requirement packs under `requirements/DEMO` demonstrate the storage
  layout. Real installations point `ConfigManager` to a writable directory.
* User configuration and logs live in the home directory (`ConfigManager._default_config_path`).
* LLM credentials (`OPEN_ROUTER`) are read from the environment or loaded via
  `.env`. The default configuration targets
  `https://openrouter.ai/api/v1` with the
  `meta-llama/llama-3.3-70b-instruct:free` model.

## Tests and checks

* Suites are documented in `tests/README.md`. Common commands:
  * `pytest --suite core -q` — unit and fast integration coverage without GUI.
  * `pytest --suite service -q` — service layer and CLI scenarios.
  * `pytest --suite gui-smoke -q` — fast GUI smoke (currently red: the
    `AgentChatPanel` ↔ `DetachedEditorFrame` path needs repair).
  * `pytest --suite gui-full -q` — full GUI regression (slow).
  * `COOKAREQ_RUN_REAL_LLM_TESTS=1 pytest --suite real-llm tests/integration/test_llm_openrouter_integration.py::test_openrouter_check_llm -q`
    — live OpenRouter integration.
* For manual GUI checks, run `python tools/run_wx.py app/ui/debug_scenarios.py --scenario main-frame` to start the frame under a
  virtual display.

## Known gaps and risks

* `pytest --suite gui-smoke -q` is failing; schedule time to restore it before
  large UI changes.
* `ThreadedAgentCommandExecutor` uses a single worker. Long LLM calls block
  subsequent commands; scaling will require coordination changes with the UI.
* The MCP server reads its requirement base path from configuration. Invalid
  paths surface as runtime errors — update documentation and configuration when
  relocating the storage directory.
* Any change to the requirement JSON schema must update the document store,
  domain models, tests and provide migration guidance for existing data.

## Checklist before starting a task

1. Re-read `AGENTS.md` and this file to confirm integration points.
2. Identify the affected layer (core, services, UI, agent, MCP, build).
3. Plan the right test suites (`pytest --list-suites` helps enumerate options).
4. Ensure environment variables (`OPEN_ROUTER`, etc.) are in place if LLM or MCP
   work is involved.
5. After implementing changes, update documentation (`docs/ARCHITECTURE.md`,
   `tests/README.md` when needed) and inspect logs for new warnings.

