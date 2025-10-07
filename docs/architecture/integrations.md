# CookaReq integrations and external interactions

> Draft scaffold: captures the section structure and the aspects that must be covered.

## 1. LLM and OpenRouter

### Default configuration
- `app.settings.LLMSettings` inherits defaults from `app.llm.constants`: base URL `https://openrouter.ai/api/v1` and model `meta-llama/llama-3.3-70b-instruct:free`. The pair provides the most stable tool-call behaviour and is used by the GUI/CLI by default.
- Reasoning-enabled smoke tests use the free `x-ai/grok-4-fast:free` model because it supports the `include_reasoning` and `reasoning` parameters without additional cost. Override the model via the `OPENROUTER_REASONING_MODEL` environment variable for operational switches.

### Configuration and secrets
- The OpenRouter key is loaded from `.env` (`OPEN_ROUTER`) and injected into tests with `tests.env_utils.load_secret_from_env`.
- The GUI and CLI allow overriding the model, URL, and message format in user settings (`settings.json`), validated by Pydantic schemas.

### Limitations and fallbacks
- Without a key or when real tests are disabled (`COOKAREQ_RUN_REAL_LLM_TESTS` unset), the scenarios in `tests/integration/test_llm_openrouter_integration.py` are skipped to avoid spurious calls.
- Argument issues are reported directly by the MCP server. `LocalAgent` forwards
  every tool call verbatim and does not attempt to validate arguments, so the
  MCP layer remains the single authority over business rules. `MCPClient`
  simply relays the server response through `app.mcp.utils.exception_to_mcp_error`.

### LLM client
- `LLMClient` remains a thin façade that selects the strategy (chat/harmony/stream) and delegates request assembly and response parsing to specialised components.
- `LLMRequestBuilder` prepares the payload: it normalises history, truncates it to the token limit, builds system blocks, and converts message formats (for example, to Qwen segments). A dedicated method constructs the Harmony prompt using the same pipeline.
- While assembling history, `LLMRequestBuilder` replaces empty user/assistant message fields with a single space. OpenRouter serialises empty strings as `null`, breaking server templates; the placeholder keeps the semantics of “no content” and prevents 500 errors during agent retries.
- `LLMResponseParser` consumes the backend response, normalises tool calls, reconstructs JSON arguments, collects reasoning segments, and converts them to `LLMReasoningSegment`/`LLMToolCall`. Recovery logic and telemetry reside in one place.
- `LocalAgent.AgentLoopRunner` accumulates reasoning fragments across every LLM turn, so even when the assistant triggers MCP tools the GUI and logs receive the full chain-of-thought that preceded the final answer.
- `LocalAgent._summarize_result` logs compact previews of the final reply together with reasoning excerpts, giving telemetry parity with the transcript’s “Model reasoning” panel.
- The façade injects a missing `rid` for `get_requirement` calls by reading the currently selected RIDs from the system message (`Selected requirement RIDs`). This smooths over models that omit identifiers and removes an extra agent/LLM turn after a `ToolValidationError`.
- The base system prompt now makes an explicit distinction between translating free-form user text (respond directly) and translating workspace data referenced by RID. For the latter the model must call `get_requirement` first, ensuring the agent always works with the up-to-date statements instead of hallucinating from the context header.
- `app.llm.logging` exposes `log_request`/`log_response` so the façade simply forwards payloads while telemetry stays centralised.
- Unit tests include stubs in `tests/unit/llm/factories.py` that swap in fake `LLMRequestBuilder`/`LLMResponseParser` instances and create synthetic `LLMResponse` objects to test LLM consumers without real network calls.

## 2. MCP server and tools
- [ ] Architecture of the MCP server (FastAPI, IPC, GUI/CLI launch sequence).
- [ ] Table of registered tools and their contracts.
- [ ] Procedure for adding new tools and testing them.

### User documentation toolset

- `list_user_documents` — returns a JSON tree (`root_entry`, `entries`) for the user-provided documentation directory, including token counts, context usage percentages, a pre-rendered ASCII tree (`tree_text`), and metadata describing the active tokenizer and read limits (`max_context_tokens`, `max_read_bytes`, `max_read_kib`). The tool works even when the root is missing, signalling the absence through an error payload so the agent can request configuration updates.
- `read_user_document` — streams numbered lines from a file while enforcing the configured byte cap. Operators control the default slice size via the MCP settings dialog (`documents_max_read_kb`, clamped to 512 KiB); agents can still request smaller reads by passing `max_bytes`. The response includes the consumed byte count, the start/end line numbers, and a `truncated` flag so the agent can resume subsequent reads.
- `create_user_document` — writes UTF-8 content to a new or existing file within the documentation root. The caller controls overwrites with the `exist_ok` flag, and responses echo the relative path plus the number of bytes written.
- `delete_user_document` — removes a single file under the documentation root. The MCP layer rejects directory paths and any attempt to escape the configured root, returning structured errors with `ErrorCode.UNAUTHORIZED` or `ErrorCode.VALIDATION_ERROR`.

### `get_requirement`

- The tool accepts a `rid` string or an array of strings. When enriching context (see `LocalAgent._fetch_requirement_summaries_async`) the agent passes an array, preserving the order from the system message and removing duplicates.
- The `fields` parameter limits the reply to two key fields (`title`, `statement`) to reduce payload size during asynchronous context requests.
- Responses always include `result.items` with `{rid, ...}` objects and an optional `missing` list. The agent skips missing RIDs and continues even when the tool returns an empty set.

### `update_requirement_field`

- The tool now returns a `field_change` block alongside the updated requirement payload. The structure mirrors `{"field": ..., "previous": ..., "current": ...}` and is derived from the persisted requirement state prior to the mutation.
- GUI summaries (`app/ui/agent_chat_panel/tool_summaries.py`) rely on this metadata to render “previous/new value” lines in tool bubbles, so the agent chat transcript explicitly shows what changed.

## 3. Filesystem and OS interaction
- [ ] File dialogs, permissions, and path handling.
- [ ] Environment requirements (wxPython, Python 3.12, dependencies).
- [ ] Cross-platform considerations and OS differences.

## 4. Other services
- [ ] Check for third-party APIs (exports, notifications, etc.).
- [ ] Capture potential integrations and constraints.
- [ ] List TODOs for further research.

## 5. Diagrams and sequences
- [ ] Identify scenarios that warrant sequence diagrams.
- [ ] Select tooling for visualisations.
- [ ] Decide where to store diagram sources and how to update them.

> Once populated, ensure the content stays consistent with `components.md` and `data_and_config.md`.
