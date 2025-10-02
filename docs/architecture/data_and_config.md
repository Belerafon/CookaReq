# CookaReq data and configuration

> Draft scaffold listing the questions to answer when describing data and settings.

## 1. Requirement repository
- [ ] Describe the structure of the `requirements/` directory and auxiliary folders.
- [ ] Document the RID file format, naming rules, and versioning approach.
- [ ] Explain loading/saving mechanics (document_store, caching, conflict handling).

## 2. Domain models and schemas
- [ ] Gather key Pydantic models and their fields.
- [ ] Note invariants and validation rules per model.
- [ ] Describe how models connect to the UI and MCP tools.

## 3. Application configuration
- [ ] List configuration sources (files, environment variables, GUI).
- [ ] Define precedence and override rules.
- [ ] Highlight sensitive parameters (LLM keys, project paths).

## 4. Agent and MCP configuration
- [ ] Outline LLM client settings, operating modes, and limits.
- [ ] Describe MCP server configuration and tool setup.
- [ ] Build a dependency table between settings and functionality.

### Agent parameters

- `agent.max_consecutive_tool_errors` — caps the number of consecutive MCP tool failures. The default value (5) lets the LLM see the error payload and adjust arguments. Non-positive values or `null` disable the guard, deferring control to `agent.max_thought_steps`.
- The requirements directory contains a `.cookareq` subfolder with `agent_settings.json`. It stores the user-defined system prompt appended to the agent’s base text for the selected project. The file sits next to the chat history (`agent_chats.json`) so domain-specific rules travel with the repository. The active conversation is kept in the sidecar `agent_chats_active.json` to avoid serialising the entire history when switching contexts. Each `ChatEntry` in `agent_chats.json` now includes a `reasoning` field: an array of segments capturing hidden model thoughts (CoT) returned by reasoning-capable OpenAI/Qwen models. Every segment records the type label, the trimmed text, and the exact leading/trailing whitespace that surrounded the fragment in the stream (`leading_whitespace`/`trailing_whitespace`). The GUI exposes these segments in the collapsible “Model reasoning” panel so operators can inspect the chain of thought and debug mistakes without losing spacing when the model streams partial words.
- `AgentLoopRunner` aggregates the reasoning segments from every LLM turn (including those that finish with MCP tool calls) before committing the final entry. As a result the persisted `reasoning` array reflects the full chain-of-thought that led to the answer, not just the last step after the tools finished.
- `llm.message_format` selects how conversations are encoded for the model. The Settings dialog offers the classic OpenAI format (`openai-chat`), Harmony (`harmony`) for GPT-OSS, and the Qwen integration (`qwen`). Qwen builds ChatML-like messages, supports reasoning models with a `reasoning_content` field, and extracts MCP tool calls even when they appear inside the reasoning stream. Harmony uses its own renderer: the system prompt, instructions, and MCP JSON schemas are converted into a Harmony sequence before the client calls the Responses API and parses `message`/`function_call` blocks, keeping CoT hidden from the user. Streaming relies on `responses.stream`, so Harmony honours cancellation the same way as other formats without fallback blocking requests.
- `llm.use_custom_temperature` and `llm.temperature` toggle whether the client sends the `temperature` parameter to OpenAI-compatible APIs. By default the checkbox is disabled and the client omits the value so providers fall back to their defaults. When enabled, the GUI exposes a `SpinCtrlDouble` with a 0–2 range (step 0.1) and a default of 0.7. `LLMClient` applies the value to every request, including health checks, and removes the parameter when the checkbox is cleared.

## 5. Data management and migrations
- [ ] Document backup and restore processes.
- [ ] Outline schema migration strategies (changing requirement structure, updating configs).
- [ ] Collect known issues (for example manual conflict resolution).

## 6. Data observability
- [ ] Identify where data and configuration operations are logged.
- [ ] List automatic checks and validations.
- [ ] TODOs for improving monitoring and diagnostics.

> When filling the section, cross-check with `integrations.md` to avoid duplicating external service descriptions.
