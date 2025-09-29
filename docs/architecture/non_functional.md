# CookaReq non-functional aspects

> Draft scaffold listing the topics to cover when documenting operations and quality.

## 1. Reliability and resilience
- [ ] Failure scenarios (MCP outage, LLM errors, missing requirement files).
- [ ] Recovery and redundancy mechanisms.
- [ ] Planned resilience improvements.

## 2. Performance and scalability
- [ ] Known bottlenecks (loading large projects, long tool calls).
- [ ] Profiling and optimisation approaches.
- [ ] Plans for parallelism and async execution.

## 3. Observability
- [ ] Logging, tracing, metrics.
- [ ] Diagnostic tooling and debugging procedures.
- [ ] TODOs for monitoring improvements.

## 4. Testing and quality
- [ ] Test pyramid (unit, integration, GUI), coverage, required suites.
- [ ] How determinism and environment isolation are ensured.
- [ ] Debt list and areas lacking tests.

## 5. UX and localisation
- [ ] User experience requirements and language support.
- [ ] GUI/CLI interaction specifics, accessibility considerations.
- [ ] Risks and improvement ideas.

## 6. Extensibility and maintenance
- [ ] Approaches for adding new features (GUI panels, MCP tools, data types).
- [ ] Versioning and compatibility policy (legacy is removed by default).
- [ ] Refactoring task plan.

> After filling this section, cross-check `components.md` to keep subsystem references up to date.
