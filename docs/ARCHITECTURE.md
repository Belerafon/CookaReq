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
| `app/resources/version.json` | Build-stamped version metadata (date only) surfaced in the main window title. The loader first tries `importlib.resources` and then falls back to filesystem paths so frozen bundles still show the version. |
| `requirements/` | Bundled sample requirements packs (`DEMO/…`). |
| `tests/` | End-to-end, GUI, services and core suites (see `tests/README.md`). |
| `tools/` | Development helpers such as `run_wx.py` for running wx scripts under a virtual display. |

## Core domain: requirements and traceability

* **On-disk layout** — each document lives under `requirements/<PREFIX>/`.
  * `document.json` stores metadata (title, parent, labels).
  * `items/<ID>.json` keeps individual requirement payloads.
  * `agent_chats.zip` retains previous agent transcripts for that document.
  * `assets/` stores attachment files referenced from requirement statements.
* **Document store** — `app/core/document_store/` exposes CRUD helpers for
  documents, items, relationship links and label collections. It keeps ID
  counters, validates JSON payloads and hides filesystem concerns from callers.
  Requirement statements are validated as Markdown (table structure, safe HTML
  subset, and URI schemes) and rejected if they exceed the maximum statement
  length so stored requirements remain previewable and export-ready.
* **Domain models** — `app/core/model.py` defines `Requirement` and supporting
  enums (status, priority, link types). The status set currently includes draft,
  in_review, approved, baselined, retired, rejected, deferred, superseded and
  needs_clarification, while verification values include not_defined,
  inspection, analysis, demonstration and test. Any schema change must stay in
  sync with the JSON representation and migrations for existing files.
  Attachments are stored as `{id, path, note}` entries, where `id` is referenced
  from Markdown statements and `path` points to the document-local assets file.
* **Search and filtering** — `app/core/search.py` provides predicates used by
  the wx models in `app/ui/requirement_model.py` to filter by text, labels and
  status. Sorting also happens in these layers.
* **Traceability** — `app/core/trace_matrix.py` builds matrices that map
  requirements to external artefacts. The GUI reuses cached document data to
  avoid expensive reloads.
* **Import/export** — `requirement_import.py`, `requirement_export.py`,
  `requirement_tabular_export.py`, and `requirement_text_export.py` convert
  between external formats and the `Requirement` dataclass while delegating all
  persistence to the document store. The tabular helper renders the
  selectable-column CSV/TSV exports, while the text helper builds the
  plain-text card exports used by the GUI export dialog and renders Markdown
  tables as ASCII grids for readability. The HTML export cards render Markdown
  in requirement sections (including single-line breaks as `<br>`), convert
  LaTeX-style formulas into MathML, and resolve attachment links to the stored
  asset paths. The same export pipeline
  can also render DOCX cards with embedded attachments, and the GUI export
  dialog uses the card renderer for HTML/DOCX alongside the tabular/text
  formats with a selectable DOCX formula renderer (plain text, MathML→OMML, PNG
  fallback, or SVG→PNG fallback). Card exports (Markdown/HTML/DOCX/PDF) omit
  empty section blocks by default and only render placeholders when the user
  enables the explicit "show empty fields" option; section/meta labels and
  enumerated metadata values (type/status/priority) are passed through gettext
  so exported cards follow the active UI locale. Metadata and section label
  definitions are centralized in `requirement_export.py` and reused by all card
  renderers to keep translations synchronized across formats. The
  export dialog keeps a single field-selection list for all formats, and the
  selected fields are applied both to tabular exports and to card exports
  (metadata/sections/links are filtered accordingly). For card-oriented formats
  (TXT/HTML/DOCX) the dialog also exposes sort mode selection (by requirement
  number, labels, source, or title) and applies the selected ordering before
  rendering cards; when label sorting is selected, card exports can group
  either by each individual label (a requirement with multiple labels appears in
  multiple groups) or by the exact label set (single group per requirement),
  plus a dedicated bucket for unlabeled requirements. Group headings are
  rendered in HTML and DOCX outputs (plus Markdown in CLI/core usage). The
  dialog also lets users toggle label background coloring for HTML and DOCX
  cards so label chips in both the legend and requirement metadata can match
  configured document label colors. Source sorting uses a natural numeric order (например, `1.2` идет перед `1.12`) to
  match the list view behavior. The GUI export flow writes
  outputs into a dedicated directory and copies the document `assets/` folder
  alongside the export file, then prompts the user to open the export folder
  with the file name shown for quick access.

## Application services and configuration context

* **`RequirementsService`** — wraps the document store with caching, consistent
  path resolution and domain-specific errors (`DocumentNotFoundError`,
  `ValidationError`). Both the GUI and automation flows consume this service
  instead of calling the core directly. When documents allow freeform labels the
  service automatically promotes every newly applied key into the owning
  document (or the nearest ancestor that permits freeform labels), synthesising
  a human-friendly title and deterministic colour before persisting the updated
  `document.json`. Label keys are treated case-insensitively: when applying
  labels the service normalises casing to the canonical key from document
  metadata, de-duplicates user input, and refuses case-only duplicates in the
  label definition editor to avoid diverging metadata. The GUI may additionally
  request a retroactive promotion that scans existing requirements and registers
  previously ad-hoc labels so that historical datasets gain the same metadata
  guarantees. The service also centralises label maintenance:
  `update_document_labels()` replaces the full definition list while recording
  rename propagation decisions and optional requirement clean-up. Thin wrappers
  (`add_label_definition()`, `update_label_definition()`,
  `remove_label_definition()`) power the MCP tools and GUI, ensuring that
  document metadata and requirement payloads stay in sync when keys change or
  disappear. `copy_requirement()` duplicates a requirement into another
  document, resetting the revision counter (unless explicitly overridden) and
  promoting any missing label definitions in the destination so the copy can be
  persisted without manual metadata curation. Attachment helpers copy uploaded
  files into `assets/` (rejecting oversized uploads) and resolve attachment IDs
  back to local file paths for preview or export flows.
* **`UserDocumentsService`** — indexes external documentation for the agent.
  It enforces size limits, token budgets and serialises directory snapshots so
  that LLM prompts only include manageable chunks. Token counters read small
  files fully, while files above 1 MiB are sampled (100 KiB) and extrapolated to
  avoid loading entire archives into memory just to display metadata. File
  creation accepts an explicit text encoding (any Python codec name) so MCP
  tools can persist non-UTF-8 artefacts while still defaulting to UTF-8. Read
  operations inspect the file with `charset-normalizer` to auto-detect the most
  probable encoding, surface the confidence/fallback status to the agent and
  decode the content with the detected codec (falling back to UTF-8 for empty or
  ambiguous inputs). When a caller requests more than the per-call byte
  allowance, `read_file()` clamps the slice to the configured limit and reports
  `clamped_to_limit`, `bytes_remaining` and the effective chunk size so higher
  layers (MCP tools, agent UI) can guide follow-up reads without surfacing
  validation errors.
* **`ApplicationContext`** — defined in `app/application.py`. It wires up
  factories for configuration management, requirement models, services, the
  local agent and the MCP controller. Both GUI and CLI entry points rely on the
  context for consistent wiring.
* **`ConfigManager`** — lives in `app/config.py` and persists UI state and
  integration settings (`llm`, `mcp`, panels, splitter positions, last opened
  document and export dialog state per directory, including card export
  placeholders for empty fields) in `~/.config/CookaReq/config.json`. It
  bridges Pydantic settings (`app/settings.py`) and runtime wx widgets.

## Agent, LLM and MCP layers

* **Local agent (`app/agent/local_agent.py`)** — orchestrates conversations by
  pairing an `LLMClient` with an `MCPClient`. It builds prompts, enforces step
  limits, handles retry windows, manages confirmation hooks and keeps a running
  transcript of decisions.
* **LLM package (`app/llm/`)** — `client.py` wraps OpenRouter, `request_builder.py`
  assembles prompt payloads, `validation.py` and `response_parser.py` normalise
  model outputs, `context.py` selects relevant requirements and user documents,
  and `tokenizer.py` estimates prompt size. The parser also tolerates malformed
  tool arguments (concatenated fragments, unescaped control characters) and can
  synthesise assistant text from reasoning segments when the model responds with
  tool calls only. The package is designed so new providers can be introduced
  behind the same `LLMClient` API.
* **MCP server (`app/mcp/`)** — `server.py` exposes HTTP endpoints for tool
  execution, `controller.py` launches and monitors the server from the GUI,
  `client.py` issues requests with idempotent confirmation tokens, while
  `tools_read.py` and `tools_write.py` implement read/write primitives against
  the document store. Label management tools (`list_labels`, `create_label`,
  `update_label`, `delete_label`) reuse the same service helpers so renames can
  optionally cascade to requirement payloads. `events.py` broadcasts completion notifications that let
  the UI refresh without reloading the entire document tree. `server.py`
  maintains a thread-safe cache of `RequirementsService` objects scoped by the
  configured base directory so repeated tool calls reuse a single instance; the
  cache is flushed automatically when the server stops or the base path
  changes.

## Graphical interface

* **Entry point** — `app/main.py` initialises locale settings, builds the
  `ApplicationContext.for_gui()` instance, then instantiates `MainFrame`.
* **Panels and views**
  * `document_tree.py` and `list_panel.py` show documents and filtered lists of
    requirements. The list panel exposes context-menu actions for cloning,
    deriving, deleting and now transferring requirements between documents via
    a modal dialog that lets users choose between copy/move semantics and the
    destination document.
  * `editor_panel.py` manages requirement editing and metadata updates,
    including a Markdown preview mode that renders statements with attachment
    links resolved to the document-local `assets/` directory.
* `agent_chat_panel/` displays the running agent transcript, batching controls
  and confirmation toggles. Users can queue follow-up prompts while a run is
  still executing; the panel surfaces the pending message in a cancellable
  banner and automatically submits it once the agent finishes. Long-running
  commands execute through `ThreadedAgentCommandExecutor` (a single-worker
  `ThreadPoolExecutor`). The panel relies on the structured payloads from
  `app/agent/run_contract.py` instead of heuristically merging raw tool
  dictionaries.
  * History persistence lives in `HistoryStore` (SQLite); after users delete all
    conversations the panel triggers a database compaction (`VACUUM`) so the
    on-disk file shrinks immediately instead of keeping freed pages.
  * `ChatEntry` maintains a small per-entry view cache with JSON-safe payloads
    and normalised display text so transcript rebuilds reuse expensive
    transformations (`normalize_for_display`, deep `make_json_safe` walks)
    instead of repeating them on every rerender.
  * Tool timelines normalise each streamed snapshot into canonical
    `ToolResultSnapshot` objects with stable IDs, status and timestamps. Repeat
    updates for the same tool merge timestamps/status and synthesise missing
    events (for example, attaching error-code tags or an "Applying updates"
    placeholder) so the transcript and log export always include a coherent
    timeline. When the LLM trace is incomplete the view model generates a
    fallback request snapshot to keep the agent response bubble and tool log in
    sync.
  * Агент формирует канонический таймлайн `timeline` внутри
    `AgentRunPayload`: он следует порядку `event_log`, включает LLM-степы,
    вызовы инструментов и маркер завершения агента. UI получает уже
    упорядоченный список и больше не должен вычислять порядок по временным
    меткам или эвристическим подсказкам. При финализации ответа панель
    объединяет стриминговые и финальные снапшоты инструментов, поднимает
    LLM preview в полноценный `LlmTrace` и повторно строит таймлайн через
    `ensure_canonical_agent_payload`, чтобы сохранённый `raw_result`
    отражал фактический порядок событий без дальнейших эвристик в UI.
    Таймлайн используется одинаково для построения карточек
    (`_build_agent_events`) и экспорта plain-текста
    (`_entry_conversation_messages`), поэтому последовательность шагов и вызовов
    инструментов единообразна во всех представлениях. Канонизация `timeline`
    логирует компактный снимок (kind, sequence, occurred_at) на уровне DEBUG,
    упрощая поиск рассинхронизаций между рантаймом и UI.
  * Для отладки порядка событий можно задать переменную окружения
    `COOKAREQ_AGENT_EVENT_LOG_DIR`: при финализации каждого обращения агентский
    `event_log` выгружается в текстовый файл через `write_event_log_debug()`,
    сохраняя последовательность `sequence` и краткие срезы полезной нагрузки.
    Дополнительно в `diagnostic.timeline_debug` записывается плоский снимок
    таймлайна (в порядке событий) с сопоставлением `llm_step`/`tool_*` записей
    и снимков инструментов, чтобы UI больше не восстанавливал порядок
    эвристиками. Если `timeline` отсутствует, слой UI пересобирает его из
    согласованных `event_log`, `llm_trace` и `tool_results`, сохраняя порядок
    `event_log` и аккуратно вставляя недостающие LLM-степы/вызовы инструментов.
    Сортировка по времени нормализуется и устойчиво обрабатывает некорректные
    метки, чтобы восстановление не падало на неожиданных форматах.
    Контроллеры и тестовые хелперы обязаны подавать уже
    канонизированный `AgentRunPayload` (согласованный `event_log`,
    `llm_trace` и `tool_results`), используя `build_agent_timeline` для
    фиксации порядка перед сохранением или рендерингом.
* `app/agent/run_contract.py` defines the shared schema for tool snapshots and
  LLM traces. Every streamed update carries a stable identifier, canonical
  status, start/finish timestamps and an ordered timeline of events. The LLM
  trace records each request/response pair so the UI can present the turn
  without guessing which payload belongs to which step.
* The transcript view (`SegmentListView`, `TurnCard`, `MessageSegmentPanel`)
  keeps a timeline cache of normalised payloads and reuses wx widgets between
  rerenders so large conversations (30+ messages) can refresh without tearing
  down the layout on every frame. Each turn caches a signature of the ordered
  agent events (`timeline.sequence`, kind, tool call id/step index) so a
  reordered or deduplicated timeline triggers a rerender even if entry IDs and
  counts stay the same.
  * `trace_matrix.py` and `derivation_graph.py` visualise relationships.
* **Controllers** — under `app/ui/controllers/`, they translate wx events into
  service calls (`DocumentsController`, `MCPController`, etc.). Controllers take
  care of ID uniqueness, validation and model updates before hitting the store.
* **Models** — `RequirementModel` caches the active requirement set in memory
  and exposes filtered views to the list panel, keeping UI updates fast.
* **Dialogs and helpers** — confirmation flows, error dialogs and settings live
  in `app/confirm.py`, `app/ui/error_dialog.py`, `app/ui/settings_dialog.py` and
  related modules. Help popups created in `app/ui/helpers.py` are modeless and
  explicitly destroyed on close so they can be reopened cleanly without stale
  state. `LabelsDialog` coordinates label edits by capturing rename propagation
  choices and deletion clean-up flags before the controller forwards the plan to
  `RequirementsService.update_document_labels()`. The export dialog
  (`app/ui/export_dialog.py`) lets users choose export scope (all requirements,
  only currently visible after filters, or only selected rows), columns and
  format before rendering output, including a text-only option for omitting or
  labelling empty fields.

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
1. The UI builds a `Requirement` from the editor panel and persists it via
   `EditorPanel.save()` (list-panel edits call
   `DocumentsController.save_requirement()` directly).
2. The controller validates uniqueness through `RequirementsService.list_item_ids()`
   and `document_store.rid_for()` before writing to disk.
3. After a successful save, the main frame and list panel update the
   `RequirementModel` and refresh derived-map state so the list view reflects
   the latest requirement content.
4. Clone/derive actions create a new `Requirement`, register it in the model via
   `DocumentsController.add_requirement()`, and persist it immediately with
   `DocumentsController.save_requirement()` to keep the UI and filesystem in sync.
5. Document creation and deletion route through `RequirementsService` to keep
   the cache consistent with on-disk state.
6. Unsaved edits are tracked in `RequirementModel` so the list panel can render
   a visual marker (a leading `*` in the Title/ID columns) and the main frame
   can offer Save/Keep/Cancel choices when navigating away from dirty entries.

### Agent and MCP interaction
1. `AgentChatPanel` gathers the current context and invokes
   `LocalAgent.respond_async()` through `ThreadedAgentCommandExecutor`.
   Разметка/сборка виджетов вынесена в `agent_chat_panel/layout_builder.py`,
   синхронизация истории — в `history_sync.py`, расчёт токенов и подтверждений —
   в `session_controller.py`, а `panel.py` остаётся тонким оркестратором, который
   соединяет подкомпоненты и проксирует публичное API.
2. The agent assembles prompts with `app/llm/context.py` and sends them via the
   LLM client. Planned tool invocations are validated before execution.
3. `MCPClient.call_tool_async()` issues HTTP requests to the local MCP server
   (`app/mcp/server.py`).
4. On success, `events.notify_tool_success` informs subscribers (UI, telemetry)
   so the requirement model refreshes without reloading everything from disk.
5. Label maintenance tools (`create_label`, `update_label`, `delete_label`)
   follow the same path: the main frame refreshes document metadata to keep the
   label dialogs in sync and applies propagated renames/removals to the
   in-memory requirements so the editor and list widgets reflect the latest
   state immediately.

### Контракт данных агентского прогона

`LocalAgent` формирует детерминированный объект `AgentRunPayload`
(`app/agent/run_contract.py`) и передаёт его в UI как `raw_result` истории
чата.

* В поле `tool_results` попадают экземпляры `ToolResultSnapshot`, описывающие
  каждое обращение к MCP: `tool_name`, аргументы (`tool_arguments`), статус
  (`running`, `succeeded`, `failed`), метрики (`ToolMetrics`) и события
  таймлайна (`ToolTimelineEvent`). Последний выполненный инструмент дублируется
  в `last_tool`, а при сбое он же проксируется в плоские ключи `tool_name`,
  `tool_arguments`, `tool_result` и `error` для обратной совместимости с
  экспортом логов.
* `llm_trace` содержит последовательность `LlmStep`: на каждый запрос LLM
  сохраняются исходные сообщения, ответ и отметка времени. Дополнительно в
  `diagnostic.llm_steps` и `diagnostic.llm_requests` откладываются снимки
  исходных сообщений для отладки ошибок валидации инструментов.
* Каждый промежуточный шаг фиксируется как событие `llm_step` без усечения:
  в `message_preview` и `reasoning` передаются исходные тексты ответа модели,
  плюс снапшоты `request_messages` и `response` (контент, tool_calls,
  reasoning). Эти данные пишутся в `diagnostic.event_log` и сразу отображаются
  в ленте чата вместе с шагами и вызовами инструментов.
* Все события и снимки инструментов маркируются явным `sequence`, равным
  порядку поступления из рантайма. UI, экспорт и история используют этот
  порядок без пересортировки по времени, чтобы таймлайн оставался линейным и
  воспроизводимым даже при отсутствующих или несовпадающих метках времени.
* Поле `diagnostic` агрегирует дополнительные сведения: ошибки MCP
  (`diagnostic.error`), причины остановки (`diagnostic.stop_reason`), полные
  снапшоты инструментов (`diagnostic.tool_results`) и вспомогательные данные,
  необходимые UI (последовательность `llm_requests`, счётчики повторных ошибок
  и т. п.).
* `tool_schemas` содержит кэш объявлений MCP-инструментов, чтобы UI мог
  локализовать аргументы и отображать корректные подсказки.

Благодаря фиксированному контракту UI и тесты используют одни и те же данные —
удалены эвристики вроде `_llm_steps`, `looks_like_tool_payload` и вспомогательные
"мерджи" словарей; история чата сериализуется и восстанавливается без потери
  метаданных.

### Как работает reasoning и превью шагов

* При отправке запроса агент кладёт reasoning-сегменты ассистента прямо в
  историю сообщений (`role="assistant"`), поэтому следующий шаг получает их
  обратно вместе с текстом предыдущей реплики. Таким образом, модель сама
  восстанавливает контекст размышлений.
* `message_preview` и reasoning — разные поля. Первое отражает основное
  содержимое ответа ассистента, второе — цепочку рассуждений, которую модель
  возвращает отдельно. Оба значения прокидываются в события `llm_step` без
  обрезки, так что их видно в журнале и прямо в чате, даже если итоговый ответ
  ещё не получен.

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
* `pytest --suite gui-smoke -q` — fast GUI smoke (17 высоко-приоритетных сценариев).
* `pytest --suite gui-full -q` — full GUI regression (slow).
  * `COOKAREQ_RUN_REAL_LLM_TESTS=1 pytest --suite real-llm tests/integration/test_llm_openrouter_integration.py::test_openrouter_check_llm -q`
    — live OpenRouter integration.
* For manual GUI checks, run `python tools/run_wx.py app/ui/debug_scenarios.py --scenario main-frame` to start the frame under a
  virtual display.

## Known gaps and risks

* `pytest --suite gui-smoke -q` покрывает минимальный happy-path. Следите, чтобы
  `pytest.mark.gui_smoke` оставался только на критичных тестах; иначе прогон
  перестанет быть лёгким.
* `ThreadedAgentCommandExecutor` uses a single worker. Long LLM calls block
  subsequent commands; scaling will require coordination changes with the UI.
* The MCP server keeps its requirement base path in sync with the directory
  opened in the main window. The settings dialog shows the value read-only so
  that only valid, user-selected folders are applied. Auto-start launches MCP
  when a requirements folder becomes active; disabling auto-start leaves MCP
  stopped until started manually from the dialog.
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
