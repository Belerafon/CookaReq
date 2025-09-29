# CookaReq system context

> Draft scaffold describing the sections and data to collect before writing the full content.

## 1. Product goal and positioning
- [ ] Summarise the problem CookaReq solves.
- [ ] Clarify how the desktop application differs from the CLI and how they complement each other.
- [ ] Capture primary usage scenarios (editing requirements, traceability, reviewing changes).

## 2. Actors and external systems
- [ ] Build a table of actors (GUI user, CLI user, LLM, MCP, filesystem).
- [ ] Describe each actor’s interests and interaction points with the system.
- [ ] Record dependencies on external services (OpenRouter, local MCP tools).

## 3. System boundaries and key flows
- [ ] Produce a textual context diagram highlighting interfaces.
- [ ] Document major data flows: loading requirements, running the agent, updating the trace matrix.
- [ ] Define data exchange constraints (formats, protocols, environment requirements).

## 4. Lifecycles
- [ ] GUI: application startup, project selection, panel interactions, shutdown.
- [ ] CLI: initialisation, command execution (export, validate, etc.), exit.
- [ ] Agent/MCP: server startup, tool registration, request handling, failures and recovery.

## 5. Constraints and assumptions
- [ ] Identify technical and organisational constraints (offline mode, wxPython dependency, supported OSes).
- [ ] Document assumptions about the data (structure of `requirements/`, file naming rules).
- [ ] Collect known risks and TODOs for future improvements.

## 6. Artefacts and references
- [ ] List diagrams to prepare (Graphviz/PlantUML).
- [ ] Link to key modules in the codebase that define the system context.

> After filling the section, revisit the roadmap to ensure neighbouring documents receive the necessary cross-links.
