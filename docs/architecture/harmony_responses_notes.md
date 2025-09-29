# Harmony / Responses protocol for LLMs

## Purpose and scope
Harmony is the dialogue representation format used by OpenAI for the gpt-oss family of models and is compatible with the Responses API. The protocol defines a unified encoding for roles, channels, and auxiliary message metadata so the model can differentiate system instructions, developer guidance, user prompts, reasoning flow, and tool calls. Unlike classic Chat Completions, Harmony mandates strict adherence to the structure and reserved tokens (`<|start|>`, `<|channel|>`, `<|message|>`, `<|end|>`, etc.) while separating tool commands from user-facing output.

## Core entities
- **Roles**: `system`, `developer`, `user`, `assistant`, `tool`. Instruction precedence matches this order (system > developer > user > assistant > tool).
- **Assistant channels**:
  - `analysis` — chain-of-thought reasoning, hidden from the user.
  - `commentary` — planned actions, tool calls, diagnostic messages.
  - `final` — user-visible response.
- **Special tokens**: `<|start|>` (200006), `<|channel|>` (200005), `<|message|>` (200008), `<|constrain|>` (200003), `<|end|>` (200007), `<|return|>` (200002), `<|call|>` (200012). They are part of the `o200k_harmony` vocabulary.

## Message structure
Every message is encoded as `<|start|>{header}<|message|>{content}<|end|>`, where the header defines the role, channel, recipient (for tools), and content type. System and developer messages typically omit the channel. Assistant messages may end with `<|return|>` (normal completion) or `<|call|>` (tool invocation); when persisted in history the closing token is replaced with `<|end|>`.

## System and developer messages
- **System**: specifies the model identity (“You are ChatGPT…”), knowledge cutoff, current date, reasoning level (`Reasoning: high|medium|low`), allowed channels, and built-in tools (browser, python, etc.). When functions are available the message also notes that calls must be emitted via `commentary`.
- **Developer**: contains system-prompt instructions and tool/format declarations. Tools are defined using TypeScript-like pseudo-typing under the `functions` namespace with descriptive comments and JSON Schema for structured outputs.

## Conversation history
When building a prompt the conversation consists of Harmony messages in order: system, developer, then alternating `user` and `assistant` entries. Assistant messages can include CoT in `analysis`, followed by a final reply or tool call. Tool responses are encoded as `tool` messages authored by `functions.<name>` on the `commentary` channel. During a follow-up request the history includes the assistant’s final message and all tool replies; reasoning chains are replayed only when the interaction ended with a tool call.

## Streaming
The Responses API delivers a stream of events: `response.stream.delta` (content chunks), `response.stream.error`, `response.completed`, `response.output_text.delta`, `response.output_tool_call.delta`, etc. Use `StreamableParser` from `openai_harmony` to track the active channel, content type, and recipient while reconstructing messages without losing Unicode sequences. The stream ends on `<|return|>` or `<|call|>`.

## Tool calls
The assistant emits a `commentary` message, sets the recipient `to=functions.<name>`, and, if necessary, adds `<|constrain|>json` to indicate the argument type. After the tool finishes, the application appends a `tool` message (`<|start|>functions.<name> to=assistant<|channel|>commentary<|message|>{output}<|end|>`). The next conversation replay must include both the CoT and the tool response so the model can continue reasoning.

## Integration tips
1. **Rendering**: use `openai_harmony.Conversation` and `load_harmony_encoding` to build token payloads. When the library is unavailable, implement a minimal renderer but keep the token format intact.
2. **Parsing**: process messages line-by-line with `StreamableParser`. For non-blocking output the Responses API exposes `responses.stream`, which emits the same events.
3. **Compatibility**: confirm that your provider supports Harmony (OpenRouter, custom inference). If not, switch to a service that offers Responses/Harmony and keep conversations in a single format.
4. **Tools**: before calling `responses.create`, flatten MCP tool definitions into `type/name/parameters` without the nested `function` block. `convert_tools_for_harmony` handles this transformation so the SDK does not require `openai.pydantic_function_tool()`.
5. **Testing**: add integration tests that simulate streaming events and verify parsing of CoT, tool calls, and the final message. Pre-recorded token sequences are useful for regression coverage.

## Additional references
- `openai_harmony` repository: renderer, parser, and token definitions.
- Responses API documentation: details the `responses.create` and `responses.stream` event structure.
- Prompt examples: keep local copies (for example under `tests/fixtures`) for debugging and onboarding.
