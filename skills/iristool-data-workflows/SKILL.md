---
name: iristool-data-workflows
description: Move local tabular files or Hugging Face/Kaggle datasets into InterSystems IRIS through iristool MCP, inspect tables, create indexes, and export local files. Use for iristool data workflows; ObjectScript development is outside this skill.
---

Use `iris_servers` to identify configured names, namespaces, write permissions,
and installed extras. Pass `server` explicitly when the user names a connection;
never substitute the default after a routing error. SQL schema and IRIS
namespace are different: tools default to schema `SQLUser` inside the configured
namespace. Pass table names without schema prefixes.

The server discovers the workspace from MCP client roots, falling back to its
launch directory. Check the workspace returned by `iris_servers` before choosing
a connection. Multiple roots in one session are ambiguous; use a separate session
per workspace or an explicit workspace override rather than guessing. File paths
resolve inside the workspace selected for that call. The server rejects paths escaping that
workspace. Credentials come from its TOML configuration or referenced environment
variables; do not include passwords or source tokens in tool arguments.

For imports:

- Inspect `iris_describe_table` when targeting a table that may already exist.
  Imports fail by default on existing tables. Use `replace=true` only when the
  user's request authorizes deleting that table's previous data. Replacement
  commits before insertion; failures can leave an empty new table.
- `iris_import_file` accepts CSV/TSV, a JSON array of row objects, JSONL, and XLSX.
  For large CSV/TSV/JSONL files use `chunk_size` and complete `column_types`.
  Explicit SQL types are required for streaming, so late chunks cannot silently
  exceed a type inferred from an early sample. Without chunking, the entire file
  is loaded into memory and types can be inferred.
- Preserve nullable integers, exact decimal requirements, and Unicode. Do not
  convert identifier columns to floats. Flatten nested JSON/media values into
  scalar columns before import. XLSX and provider imports currently materialize
  a DataFrame; use an HF split slice or a selected Kaggle file to limit size.
- HF accepts `split`, `config_name`, and `revision`; use a revision when
  reproducibility matters. Kaggle accepts versioned dataset handles and `file`.
  Private sources use the selected workspace's provider token configuration.
  If access is denied, resolve source permissions rather than retrying downloads.
- Check the returned row count and inspect resulting types with
  `iris_describe_table`. Do not report success after a tool error. Multi-file
  Kaggle imports are not atomic: earlier tables may already have loaded.

Create requested secondary indexes with `iris_create_index` after bulk imports.
Choose columns and index types for the intended query; do not add indexes to
all columns. Creating a unique index can fail if existing data has duplicates.

`iris_export_table` writes local CSV, JSON records, JSONL, or XLSX. CSV/JSON/JSONL
use bounded chunks; XLSX holds the full table in memory and returns `rows=null`.
Existing files fail unless `overwrite=true`; failed exports preserve the old
file. Exports have no guaranteed row order. Verify the returned path and row count
when available. The server does not publish datasets to HF or Kaggle.

Provider credentials come from the selected workspace's `[providers.huggingface]`
and `[providers.kaggle]` TOML sections (`token` or `token_env`). Do not pass secrets
in tool calls. HF without a token uses anonymous access; Kaggle requires a
workspace token. Restart the server after editing a loaded configuration.

For subset exports, pass `columns`, ANDed `filters` (`column`, `op`, `value`),
`order_by` (`column`, `direction`) and `limit` to `iris_export_table`. Consult
`iris_describe_table` first. Use NULL operators without a value; IN takes a
non-empty scalar list. Order by a unique key for reproducible limited results.
Do not put SQL expressions or fragments in selection fields. Selection runs
inside IRIS and the result streams through the shared atomic file writer.
Raw `export_query()` is available only to Python callers using database account
permissions; it is not a read-only SQL validator.
