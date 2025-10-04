# Agent history migration

Starting with the release that introduced this note, the agent chat history is
stored exclusively in **version 2** format. Every conversation entry carries a
mandatory `token_info` block, and the application refuses to load files that use
other versions or omit the field. The policy simplifies the loading code,
eliminates implicit migrations during startup, and guarantees that the GUI
always displays an accurate token count.

The same release added the `token_cache` dictionary to each `ChatEntry`. It holds
hashes of the prompt/response text and cached `TokenCountResult` values per LLM.
Older entries without this field remain valid: CookaReq will populate the cache
in memory and persist it on the next history update.

Legacy archives must be converted before opening them in the application. The
repository provides a helper script, `tools/migrate_agent_history.py`, for this
purpose.

## Supported input layouts

The script understands two legacy shapes:

1. **Version 2 files without `token_info`**. In these entries the `tokens` field
   may have been filled manually and token metadata is missing. The utility
   recomputes the statistics from text and appends the `token_info` block to each
   record.
2. **A flat list of dictionaries** without the `{"version": ..., "conversations": ...}`
   wrapper. The script creates a new conversation, copies entries into it, and
   derives missing fields. The last successfully migrated conversation becomes
   active.

Files with unknown versions (for example `version: 3`) are rejected to avoid
corrupting data.

## Usage

```bash
python3 tools/migrate_agent_history.py /path/to/history.json
```

By default the result is written next to the source file with the `.migrated`
suffix (for example, `history.migrated.json`). To overwrite the file in place and
create a backup at the same time, add `--in-place`:

```bash
python3 tools/migrate_agent_history.py /path/to/history.json --in-place
```

The backup lives alongside the original with the `.bak` extension. Specify a
custom path via `--backup`, and use `--force` to overwrite existing output or
backup files.

After migration, launch the application and confirm that the chat history opens
without incompatible-format warnings. To roll back, replace `history.json` with
the backup and rerun the migration after addressing the reported issue.

## Known limitations

- Older formats did not store conversation timestamps. During migration the
  script reconstructs `created_at` and `updated_at` from the first available
  `prompt_at`/`response_at` values. When they are absent, the current time is
  used.
- Severely corrupted files (for instance, entries that are not dictionaries) are
  skipped. If no valid records remain, the utility raises an exception.
- The script copies `raw_result` verbatim (including any embedded
  `tool_results` payloads). If the structure changes between releases, review
  the output manually.

## Testing and maintenance

- Before shipping new history formats, run the GUI unit tests. They confirm that
  the application rejects outdated files instead of silently migrating them.
- Whenever the history schema evolves, update the loader code and this document
  so users know how to prepare their data in advance.
