# CookaReq

CookaReq (Cook a requirement) is a wibecoded desktop application built with wxPython for managing requirements stored in separate JSON files. The package includes a graphical interface, a command-line utility and an MCP server for integration with LLM agents.

## Features

- Organize requirements into hierarchical documents. Each document stores
  its configuration in `document.json` and individual items as
  `items/<ID>.json` files. File names use only the zero-padded numeric
  identifier, while the full requirement ID (RID) is composed at runtime
  from the document prefix and that number. Revisions are tracked per item.
- Search by text, status and labels with advanced filters
- Create, clone, edit and delete requirements; attach files and manage user labels
- Navigate links between requirements and visualise derivation graphs
- Persistent interface state: window size, columns, sorting, recent folders
- Command dialog for interacting with the built-in LocalAgent (LLM + MCP)
- Settings dialog for configuring LLM, MCP and UI options
- Manage label presets and choose colours for custom labels
- Display document hierarchy in a tree and switch between documents
 - Editor and requirement list respect labels inherited from the selected document and
   allow free-form entries when any parent document permits them
 - Command-line utility for managing documents and items, linking and tracing requirements, performing migrations and health checks
- MCP server exposing requirement tools for external agents
- Interface localization via text `.po` files

## Graphical Interface

The main window is divided into three panes:

1. **Document tree** — shows documents with their parent–child relationships.
2. **Requirement list** — a table with customizable columns. Supports sorting, label filters, text search and an extended filter dialog. The context menu lets you create new requirements, clone existing ones and delete entries. Deleting entries prompts for confirmation and shows the requirement's RID and title to prevent accidental removal.
3. **Editor** — a form with the fields of a requirement model. It appears when creating or editing a record and allows saving changes to a file.

Selecting a document updates the requirement list and editor with the items and label presets defined for that document and its ancestors. If any document in the chain enables free-form labels, the selection dialog accepts additional custom names.

Additional windows and dialogs:

- **Command dialog** — run LocalAgent commands that combine LLM reasoning with MCP tools.
- **Settings dialog** — edit LLM/MCP/UI configuration stored in a JSON or TOML file.
- **Labels dialog** — manage label presets; the **label selection dialog** picks labels from predefined sets with generated colours.
- **Filter dialog** — build complex search queries across fields, labels and statuses.
- **Derivation graph** — visualise "derived-from" links using `networkx` and Graphviz.
- **Navigation** — jump between linked requirements.

An optional log console is shown at the bottom of the window. Interface settings and the last opened directories are preserved between sessions.

## Command-Line Interface

The CLI lives in the `app/cli` package. Example usage:

```bash
python3 -m app.cli <command> [arguments]
```

Subcommands:

- `doc create <root> <PREFIX> <title> [--digits N] [--parent P]` — create a document
- `doc list <root>` — list existing documents
- `doc delete <root> <PREFIX> [--dry-run]` — delete a document

- `item add <root> <PREFIX> --title T --statement S [--labels L1,L2]` — add a requirement to a document
- `item move <root> <RID> <NEW_PREFIX>` — move a requirement to another document
- `item delete <root> <RID> [--dry-run]` — delete a requirement and update references

- `link <root> <RID> <PARENT...> [--replace]` — connect a requirement to ancestor items
- `trace <root> [--format plain|csv|html] [-o FILE]` — export links as a trace matrix
- `check [--llm|--mcp]` — verify LLM and MCP connectivity according to loaded settings

Commands that modify data validate input JSON and labels before saving. If validation fails, no changes are written to disk. The `check` command uses the same LocalAgent as the GUI to test LLM and MCP access. This agent is imported lazily, so running `--help` or unrelated commands does not require LLM/MCP dependencies.


## MCP Integration

CookaReq includes an MCP server that exposes requirement tools to external agents and the built-in LocalAgent. Available tools cover reading, searching and mutating requirements (`list_requirements`, `get_requirement`, `search_requirements`, `create_requirement`, `patch_requirement`, `delete_requirement`, `link_requirements`). Search-related tools accept a `labels` parameter to filter results. The LocalAgent combines these tools with an LLM client and is accessible from the GUI command dialog or the CLI `check` command.

## Requirements Repository

Requirements live in a hierarchical document tree under the `requirements/` directory:

```
requirements/
  SYS/
    document.json
    items/
      001.json
  HLR/
    document.json
    items/
      001.json
```

The repository layer loads and saves items, manages label presets defined by each document and resolves links across documents. Advanced search parameters allow filtering by status, label combinations, field-specific queries and derived relationships.

### File Format

Each document file (`document.json`) includes:

- `title` *(str)* — human-readable name
- `digits` *(int)* — width of numeric identifier padding
- `parent` *(str|null)* — parent document prefix or `null`
- `labels` *(object)* — label definitions and an `allowFreeform` flag
- `attributes` *(object)* — additional metadata

The document prefix matches the folder name under `requirements/` and is no longer duplicated inside `document.json`, keeping the identifier as a single source of truth.

Each requirement item (`items/<ID>.json`, where `<ID>` is the zero-padded numeric identifier) includes:

- `id` *(int)* — numeric identifier unique within the document
- `title` *(str)* — short name
- `statement` *(str)* — requirement statement
- `type` *(str)* — `requirement`, `constraint`, `interface`
- `status` *(str)* — `draft`, `in_review`, `approved`, `baselined`, `retired`
- `owner` *(str)* — responsible person
- `priority` *(str)* — `low`, `medium`, `high`
- `source` *(str)* — origin of the requirement
- `verification` *(str)* — method of verification
- `labels` *(list[str])* — labels including inherited ones
- `links` *(list[str])* — linked higher-level requirement IDs
- `attachments` *(list[obj])* — attachments `{path, note}`
- `revision` *(int)* — manual revision number maintained by the author; CookaReq keeps the value as provided
- `notes` *(str)* — additional comments

## Localization

Translations are stored as plain text `.po` files and loaded at runtime, so no
compilation to binary `.mo` catalogs is required.

## Development

Run the full test suite with `pytest -q`. GUI tests are executed headless via
`pytest-xvfb`, so no display server is required.

For a rapid health check, execute the smoke tests:

```bash
pytest -m smoke -q
```

## License

This project is distributed under the [Apache License 2.0](LICENSE).

© 2025 Maksim Lashkevich & Codex.
