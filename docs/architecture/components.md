# CookaReq subsystems and layers

> Draft scaffold: outlines the sections and questions that must be answered when the document is filled in.

## 1. Layer map
- [ ] Summarise each layer (GUI, core/document store, agent, MCP, CLI, shared services).
- [ ] Define interaction rules between layers and the allowed dependencies.
- [ ] Decide on a diagram format (text matrix/Graphviz) and record where it will live.

## 2. GUI
- [ ] Describe the GUI responsibilities and its boundaries relative to the core.
- [ ] Highlight the key controllers/panels and their APIs.
- [ ] Document the interactions with the agent and the document store.
- [x] `EditorPanel`, `DetachedEditorFrame`, and the main-window mixins now work through `RequirementsService`, so ID uniqueness checks, link loading, and requirement persistence no longer depend on `app/core/document_store` directly.
- [x] `RequirementImportDialog` imports CSV/Excel files: the user configures the delimiter, maps columns to requirement fields, previews the table, and sends the data to `MainFrameDocumentsMixin` for saving.

### Agent panel batch mode

- `AgentChatPanel` spawns an `AgentBatchRunner` that manages the queue of requirements and sequentially drives `AgentRunController`. The runner receives a `BatchTarget` (RID, ID, title) and creates a fresh `ChatConversation` for every iteration without reloading previous history.
- `MainFrameAgentMixin` provides `_agent_batch_targets()` and `_agent_context_for_requirement()`, generating the requirement list and per-item system context. Both callbacks are passed to `AgentChatPanel` during initialisation.
- The panel footer exposes a “Batch queue” block with a progress bar, a table of states (`pending`, `running`, `completed`, `failed`, `cancelled`), and “Run batch”/“Stop batch” buttons. The queue visualises progress and collapses once it empties.
- `_finalize_prompt()` and the cancellation handler `_finalize_cancelled_run()` notify `AgentBatchRunner` about each step so it can advance to the next requirement or close the batch gracefully.

### Agent panel view–model–controller

- The UI layout now lives in `AgentChatView` (`app/ui/agent_chat_panel/components`). It encapsulates widget creation and operations such as toggling the waiting state. `AgentChatPanel` receives references via the returned `AgentChatLayout`.
- `AgentChatView` renders waiting/ready status strings based on token counts and the context limit provided by `AgentChatSession`, keeping this logic out of the controller.
- The state ( `AgentChatHistory`, timer, token counters) moved into `AgentChatSession`. It emits events (`running_changed`, `tokens_changed`, `elapsed`, `history_changed`) so the controller or external code can sync the UI without touching private fields.
- `AgentChatPanel` subscribes to the session events and refreshes the status, history, and conversation headers through `AgentChatView`. Timers and token updates no longer manipulate widgets directly from the controller.
- The new `AgentChatCoordinator` links the session, `AgentRunController`, and the command executor. The UI talks only to its public methods for prompt submission, stop/cancel, and batch actions, while backend feedback flows through `AgentRunCallbacks` into `AgentChatSession`.
- During regeneration `AgentRunController.regenerate_entry()` asks the panel to remove the latest message. `AgentChatPanel` returns a `RemovedConversationEntry`, persists history, and redraws the transcript immediately. If the agent fails before adding a new entry, the controller triggers the undo callback, restoring the previous message with original timestamps so the user keeps context and avoids duplicate prompts.
- Transcript rendering is now driven by segment-oriented data from `app/ui/agent_chat_panel/view_model.py`. `build_transcript_segments()` flattens every `ChatEntry` into a deterministic sequence of user, agent, tool, and system segments with stable identifiers. `SegmentListView` diffs those segments to keep the UI stable while new diagnostics stream in. Each turn renders through a `TurnCard`: a `MessageSegmentPanel` shows the user prompt with context alongside the agent responses and diagnostics, while every tool call expands into its own `ToolCallPanel` that carries the summary, arguments, and raw payload collapsibles. Reasoning steps, LLM requests, and the raw agent payload also live on dedicated collapsible sections below the agent message instead of being embedded in `MessageBubble` footers, so widgets no longer detach when the entry updates.
- Entries render in the natural conversation order. Within a turn the view model preserves the model's own sequencing: streamed responses reuse the numeric step index from the diagnostic payload (falling back to the emission order), and tool calls are sorted chronologically using the `sort_tool_payloads()` helper. This keeps the transcript stable even when diagnostic sections arrive late.
- Tool call panes show a compact overview: the summary bubble now includes status, duration, cost, error headlines, and the key arguments so operators do not have to expand collapsibles to understand what happened. The single "Raw data" collapsible exposes the combined LLM exchange (request/response pairs plus synthetic data when the backend omits the request), replacing the previous spread of summary/arguments/request/response panels and the verbose raw tool payload dump. When the agent runtime fails to persist the LLM request we still synthesise it from the recorded tool arguments so the bubble, raw view, and GUI tests surface what the model attempted to execute.

## 3. Core and requirement storage
- [x] Introduced `app.services.requirements.RequirementsService`, which encapsulates document store operations and provides a shared API for the GUI, CLI, and MCP.
- [ ] Describe requirement models, document store services, and revision rules.
- [ ] List public extension points (new document types, plugins).
- [ ] Capture filesystem and configuration dependencies.

## 4. Agent and LLM
- [ ] Explain `LocalAgent`, the operation scheduler, and LLM usage.
- [ ] Detail how the agent interacts with MCP and the document store.
- [ ] Collect risks and TODOs (e.g. threading limits, long-running operations).
- [x] `MCPClient` now forwards tool invocations to MCP without local schema
      validation. The server remains the source of truth for argument checks,
      while the client focuses on transport, confirmation prompts, and
      telemetry. Any payload issues are surfaced directly from MCP in the
      command transcript.

### Agent context enrichment hints

- `LocalAgent._prepare_context_messages_async()` normalises the system context and forwards it to `_enrich_workspace_context_async()` to populate the `[Workspace context]` block with brief excerpts from selected requirements. The method parses the `Selected requirement RIDs:` line, ignores invalid RIDs, and keeps the order of valid identifiers.
- `_enrich_workspace_context_async()` composes a single MCP request: `_fetch_requirement_summaries_async()` calls the `get_requirement` tool with the RID list and selected fields (`title`, `statement`). MCP returns an array of objects; the agent appends `RID — summary` lines, skipping entries already present. Duplicate identifiers are filtered before reaching MCP, so each context message triggers at most one tool invocation.
- If the MCP call fails or the response is malformed, context enrichment is skipped to avoid blocking the main scenario. Consider telemetry for such failures if enrichment becomes critical to the UX.

## 5. MCP and tools
- [ ] Provide an overview of the MCP server, registered tools, and their contracts.
- [ ] Note the tool lifecycle, error handling, and logging strategy.
- [ ] List the code locations used to register new tools.

## 6. CLI
- [x] CLI commands rely on `RequirementsService`, decoupling them from the `document_store` filesystem layer.
- [ ] Explain how the CLI reuses the core services.
- [ ] Highlight major commands and extension points.
- [ ] Document environment specifics (headless execution, configuration files).
- [x] Requirement export: `python3 -m app.cli export requirements` gathers data through `app/core/requirement_export.py` and produces Markdown/HTML/PDF reports with clickable RID links.

## 7. Shared services
- [ ] Catalogue helper modules (configuration, localisation, logging, plugins).
- [ ] Describe dependencies and usage rules.
- [ ] Identify potential refactoring areas.
- [x] `app.application.ApplicationContext` acts as the composition root. It lazily creates `ConfigManager`, `RequirementModel`, `RequirementsService` factories, `LocalAgent`, `MCPController`, and configures confirmation handlers. Both front ends (`app/main.py` and `app/cli/main.py`) receive dependencies through this context: the GUI passes factories to `MainFrame`, while the CLI hands the context to commands, removing the need for repeated service wiring or confirmation callbacks. `MainFrame` and CLI commands no longer create default contexts; dependencies must be provided from the composition root, eliminating hidden singletons in tests and production. Even helper windows such as `SettingsDialog` obtain `MCPController` through a factory supplied by the frame, making injection verifiable in unit tests without monkeypatching global constructors.

## 8. Interaction scenarios
- [ ] Prepare 2–3 end-to-end journeys (opening a project, editing a requirement, generating a report).
- [ ] For each journey, describe the sequence of interactions across layers.
- [ ] Decide whether to include sequence diagrams or tables.

## 9. Risks and tasks
- [ ] Collect known issues and mitigation ideas.
- [ ] Record automation opportunities (diagram generation, dependency checks).

> After completing this section ensure the system context and data/configuration documents contain matching references.
