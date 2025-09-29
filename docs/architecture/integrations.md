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
- Tool validation errors are mapped via `app.mcp.utils.exception_to_mcp_error` into the agent response, preventing infinite retries when arguments are invalid.

### LLM client
- `LLMClient` remains a thin façade that selects the strategy (chat/harmony/stream) and delegates request assembly and response parsing to specialised components.
- `LLMRequestBuilder` prepares the payload: it normalises history, truncates it to the token limit, builds system blocks, and converts message formats (for example, to Qwen segments). A dedicated method constructs the Harmony prompt using the same pipeline.
- While assembling history, `LLMRequestBuilder` replaces empty user/assistant message fields with a single space. OpenRouter serialises empty strings as `null`, breaking server templates; the placeholder keeps the semantics of “no content” and prevents 500 errors during agent retries.
- `LLMResponseParser` consumes the backend response, normalises tool calls, reconstructs JSON arguments, collects reasoning segments, and converts them to `LLMReasoningSegment`/`LLMToolCall`. Recovery logic and telemetry reside in one place.
- The façade injects a missing `rid` for `get_requirement` calls by reading the currently selected RIDs from the system message (`Selected requirement RIDs`). This smooths over models that omit identifiers and removes an extra agent/LLM turn after a `ToolValidationError`.
- `app.llm.logging` exposes `log_request`/`log_response` so the façade simply forwards payloads while telemetry stays centralised.
- Unit tests include stubs in `tests/unit/llm/factories.py` that swap in fake `LLMRequestBuilder`/`LLMResponseParser` instances and create synthetic `LLMResponse` objects to test LLM consumers without real network calls.

## 2. MCP server and tools
- [ ] Architecture of the MCP server (FastAPI, IPC, GUI/CLI launch sequence).
- [ ] Table of registered tools and their contracts.
- [ ] Procedure for adding new tools and testing them.

### `get_requirement`

- The tool accepts a `rid` string or an array of strings. When enriching context (see `LocalAgent._fetch_requirement_summaries_async`) the agent passes an array, preserving the order from the system message and removing duplicates.
- The `fields` parameter limits the reply to two key fields (`title`, `statement`) to reduce payload size during asynchronous context requests.
- Responses always include `result.items` with `{rid, ...}` objects and an optional `missing` list. The agent skips missing RIDs and continues even when the tool returns an empty set.

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
