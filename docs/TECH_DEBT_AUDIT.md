# Technical debt audit (2026-02-22)

## Critical risks

1. **Race conditions in MCP request processing**: `RequirementsServiceCache` keeps shared `RequirementsService` instances per root, while `RequirementsService` stores mutable `_documents` cache without internal locking. Concurrent HTTP requests can interleave reads/writes and produce stale or inconsistent state.
2. **Global mutable confirmation callbacks**: `ApplicationContext` calls `set_confirm()`/`set_requirement_update_confirm()` during initialization, mutating module-level globals in `confirm.py`. This couples GUI/CLI contexts and creates hidden side-effects for tests and multi-context runs.
3. **Potential indefinite wait in cross-thread confirmation bridge**: `_call_in_wx_main_thread` waits on `threading.Event().wait()` without timeout and without watchdog path; a missed `CallAfter` callback can freeze worker flow.

## Refactoring priorities

1. Split `LocalAgent` into smaller orchestrator/services:
   - interaction loop,
   - MCP tool execution,
   - error normalization,
   - telemetry/trace builders.
2. Reduce UI god-classes (`EditorPanel`, `ListPanel`, `MainFrame`) into composition of smaller controllers/view models.
3. Separate persistence and view-state concerns in `ConfigManager`; group typed settings IO and raw widget state storage into dedicated collaborators.

## Notable technical debt

- Broad `except Exception` usage across core runtime paths makes failure modes opaque and may hide programmer errors.
- Synchronous filesystem operations in UI save flows risk GUI stalls under slow disks/networked folders.
- MCP server module combines HTTP app setup, middleware, tools metadata, runtime lifecycle and logging; this increases blast radius of changes.

## Candidate backlog tasks

1. Introduce per-document locking (or immutable snapshots + CAS) for requirement writes in MCP service layer.
2. Replace global confirmation registry with explicit dependency injection into MCP/agent flows.
3. Add timeout + error telemetry to `_call_in_wx_main_thread` waiting path.
4. Extract `LocalAgent` loop core into dedicated module with contract tests around cancellation/retry/tool-error limits.
5. Add async/off-main-thread wrappers for heavy editor save/load operations.
6. Split `mcp/server.py` into: app factory, auth/logging middleware, lifecycle manager, tool registry.

