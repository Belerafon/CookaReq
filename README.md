# CookaReq

CookaReq is a desktop application built with wxPython for managing requirements stored in separate JSON files. The package includes a graphical interface and a command-line tool for batch operations.

## Features

- Store requirements as independent `id.json` files
- Open a directory and automatically load the list of requirements
- Filter by labels and perform full-text search across multiple fields
- Create, clone, edit, and delete requirements
- Version control with a revision counter and last modification date
- Support for attachments and user-defined labels
- Error log that can be hidden or shown
- Remembers window size, selected columns, sorting, and recently opened folders
- Interface localization via text `.po` files

## Graphical Interface

The main window is divided into two parts:

1. **Requirement list** — a table with customizable columns. Supports sorting, label filters, and text search. The context menu lets you create new requirements, clone existing ones, and delete entries.
2. **Editor** — a form with the fields of a requirement model. It appears when creating or editing a record and allows saving changes to a file.

An optional log console is shown at the bottom of the window. Interface settings and the last opened directories are preserved between sessions.

## Command-Line Interface

The CLI lives in the `app.cli` module. Example usage:

```bash
python3 -m app.cli <command> [arguments]
```

Available commands:

- `list <dir>` — print the list of requirements; supports `--labels`, `--query`, and `--fields` for filtering
- `add <dir> <file>` — add a requirement from a JSON file
- `edit <dir> <file>` — update an existing requirement with data from a file
- `delete <dir> <id>` — remove a requirement by id
- `show <dir> <id>` — display the full contents of a requirement as JSON

## MCP Integration

The application exposes a Model Context Protocol (MCP) server for interaction with LLM agents.
MCP tools such as `list_requirements` and `search_requirements` use the parameter `labels`
to filter requirements by their labels.

## Requirement File Format

Each requirement is stored in its own `<id>.json` file and contains the following fields:

- `id` *(int)* — unique identifier
- `title` *(str)* — short name
- `statement` *(str)* — requirement statement
- `type` *(str)* — one of: `requirement`, `constraint`, `interface`
- `status` *(str)* — `draft`, `in_review`, `approved`, `baselined`, `retired`
- `owner` *(str)* — responsible person
- `priority` *(str)* — `low`, `medium`, `high`
- `source` *(str)* — origin of the requirement
- `verification` *(str)* — `inspection`, `analysis`, `demonstration`, `test`
- `acceptance` *(str, optional)* — acceptance criteria
- `conditions` *(str)* — conditions
- `trace_up` *(str)* and `trace_down` *(str)* — traceability links
- `version` *(str)* and `modified_at` *(str)* — version and date of modification
- `units` *(object, optional)* — {`quantity`, `nominal`, `tolerance`}
- `labels` *(list[str])* — custom labels
- `attachments` *(list[obj])* — attachments `{path, note}`
- `revision` *(int)* — revision number (starting at 1)
- `approved_at` *(str, optional)* — approval date
- `notes` *(str)* — additional comments

## Localization

Translations are stored as plain text `.po` files and loaded at runtime, so no
compilation to binary `.mo` catalogs is required.

## Development

Install the package along with development dependencies:

```bash
pip install .[dev]
```

## License

This project is distributed under the [Apache License 2.0](LICENSE).

© 2025 Maksim Lashkevich & Codex.
