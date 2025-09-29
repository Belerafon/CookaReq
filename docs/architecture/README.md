# CookaReq architecture workspace

The `docs/architecture/` directory is a personal working set of notes about the CookaReq architecture. I am currently the sole maintainer, so the format is optimised for regaining context quickly before touching the code. The first goal for this iteration is to rewrite the architectural overview completely, keeping it concise yet useful instead of dumping exhaustive module lists.

## Package layout

| File | Role | Current state |
| --- | --- | --- |
| [`system_context.md`](system_context.md) | System context: product purpose, actors, key user journeys, and lifecycle diagrams. | skeleton (needs content) |
| [`components.md`](components.md) | Subsystem and layer map, their responsibilities, and extension points. | skeleton (needs content) |
| [`data_and_config.md`](data_and_config.md) | Data domains, storage formats, configuration sources, and migration rules. | skeleton (needs content) |
| [`integrations.md`](integrations.md) | Integrations with external services, LLM, MCP, and the OS. | skeleton (needs content) |
| [`non_functional.md`](non_functional.md) | Non-functional concerns: operations, testing, extensibility. | skeleton (needs content) |

Supporting materials (diagram sources, temporary code excerpts) can live next to the documents, but once a milestone completes they should either be merged into the main text or removed.

## Editing principles

* **Scenarios over file listings.** Capture key lifecycles and interactions rather than enumerating every module.
* **Local links.** Add source paths for every mentioned component so jumping to code stays quick.
* **No legacy leftovers.** When a document uncovers an outdated pattern, log a follow-up task to revisit the architecture or implementation.

## Rewrite plan

1. [x] **Package structure.** Prepare file scaffolds and document each section's purpose (current step).
2. [ ] **System context.** Populate `system_context.md` with the product goal, actors, high-level flows, and lifecycle diagrams.
3. [ ] **Subsystem map.** Fill in `components.md` with layers, dependencies, and interaction scenarios.
4. [ ] **Data and configuration.** Describe models, formats, and migrations in `data_and_config.md`.
5. [ ] **Integrations.** Document LLM, MCP, and OS integration points in `integrations.md`.
6. [ ] **Non-functional aspects.** Summarise operations, testing, and extension strategy in `non_functional.md`.
7. [ ] **Final review.** Align cross-links, task lists, and terminology.

After each step, check for related updates in neighbouring files and adjust links or vocabulary as needed.

## Preparation for the next phase

* Compile a list of actors and external systems.
* Capture the main user workflows (GUI, CLI, agent).
* Outline lifecycle diagrams for application startup, agent sessions, and requirement repository updates.

These notes will feed directly into the upcoming system context chapter.
