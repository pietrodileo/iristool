# iristool MCP server

The optional MCP server uses Python and FastMCP. It runs locally over stdio and
connects to IRIS through the official Python driver on the SQL SuperServer port.
[Install uv](https://docs.astral.sh/uv/getting-started/installation/) first. You do not need Docker, a standalone executable, or Python
packages installed on the IRIS server.

## Contents

- [Recommended setup](#recommended-setup)
- [Installation](#install-and-run), [upgrades](#upgrade-the-mcp-server) and [optional extras](#optional-extras)
- [Workspace and fleet configuration](#workspace-configuration), [read-only connections](#read-only-connections) and [workspace discovery](#workspace-discovery)
- [MCP client configuration](#mcp-client-configuration): [Cursor](#cursor), [Claude Code](#claude-code), [Codex](#codex)
- [Tools](#tools)
- [Imports and performance](#imports-and-performance), [export subsets](#export-subsets) and [provider credentials](#dataset-imports-and-credentials)
- [Companion skill](#companion-skill)
- [Uninstall](#uninstall)
- [Validation](#validation-and-distribution) and [two-instance fleet tests](#test-a-two-instance-fleet)

## Recommended setup

[Install uv](https://docs.astral.sh/uv/getting-started/installation/), then use the configuration for your client:

| Client | Configuration | Workspace selection |
| --- | --- | --- |
| [Cursor](#cursor) | Project `.cursor/mcp.json` | Cursor expands `${workspaceFolder}` |
| [Claude Code](#claude-code) | Project `.mcp.json` | MCP roots report the folder where the session started |
| [Codex](#codex) | `.codex/config.toml` or `~/.codex/config.toml` | Launch the CLI from the project; GUI fallback uses an explicit directory |

The configurations below recommend `iristool[all]` for MCP, Excel, Hugging Face
and Kaggle support. For a smaller installation, choose [optional extras](#optional-extras).

Create a `.iristool.toml` in each project using the
[workspace and fleet example](#workspace-configuration). The client-specific
sections below include copyable configurations. `${workspaceFolder}` is Cursor
syntax; do not copy it into another client's configuration.

The first `uvx` launch downloads the dependencies; later launches reuse uv's
cache. The recommended package includes Excel and both dataset providers.
For a persistent installation, use [Install once](#option-1-install-once).
After configuring the server, ask your agent to call `iris_servers` and check
that its returned `workspace` is the project you intended.

Install the optional `iristool-data-workflows` skill in your agent using its
skill installer, or copy the repository's `skills/iristool-data-workflows/`
directory into the skills directory your agent reads. See
[skill installation](#install-the-companion-skill) for details.

For example, in Codex, ask:

> Use $skill-installer to install skills/iristool-data-workflows from the
> GitHub repository pietrodileo/iristool.

Then ask your agent: "Use the iristool-data-workflows skill for this task."
Use your client's skill invocation syntax if it has one.

## Install and run

Choose either a persistent installation or automatic downloads through `uvx`.
Both use the same workspace configuration and support multiple workspaces.

### Option 1: Install once

Install the command once for your user account, then use it across workspaces:

```bash
uv tool install 'iristool[all]'
```

After installation:

1. Use your [client's configuration](#mcp-client-configuration), replacing
   `uvx` and its package arguments with the installed `iristool-mcp` command.
   Keep any workspace arguments shown for that client.
2. In each project folder, create a `.iristool.toml` containing the IRIS
   connections you want to use for that project.
3. Open a project and use the iristool tools. The server reads that project's
   connection settings, provided your editor tells it which folder you opened.

For example, you could have two projects with different connections:

```text
projects/
  sales/
    .iristool.toml     # connections for the sales project
  research/
    .iristool.toml     # connections for the research project
```

Opening `sales` selects the connections in `sales/.iristool.toml`. Opening
`research` selects the connections in `research/.iristool.toml`. Both use the
same iristool installation. You can work in both projects at once, with a
separate MCP session for each.

Automatic selection depends on your editor or agent. It must tell iristool
which project folder you opened, or start iristool from that folder. If it does
neither, iristool cannot choose the project's configuration automatically.
See [workspace discovery](#workspace-discovery) for the technical details and
how to select a folder explicitly.

Opening another project does not require reinstalling iristool. To update the
shared installation, run `uv tool upgrade --all`.

### Option 2: Run with uvx

With uv installed, your MCP client can run iristool directly without a separate
`uv tool install` step. Set its command to `uvx` and its arguments to
`["--from", "iristool[all]", "iristool-mcp"]`. See the
[client configuration examples](#mcp-client-configuration) below.

The equivalent terminal command is:

```bash
uvx --from 'iristool[all]' iristool-mcp
```

The first launch downloads iristool, its dependencies and, if needed, Python.
With `uvx`, later launches reuse its cache while it is available. With
`uv tool install`, launches use the installed environment. The iristool wheel
is small, but pandas and the other dependencies still take download time and
disk space.
Pin the package version in your client configuration to reproduce an installation.
The library supports Python 3.10+; the MCP extra uses FastMCP 2.14.x and `tomli`
on Python 3.10.

`uvx` can keep using a cached version after a new release is published.
See [upgrade instructions](#upgrade-the-mcp-server) for installed tools.

### Upgrade the MCP server

To upgrade all tools installed with `uv tool install`, including iristool, run:

```bash
uv tool upgrade --all
```

Then restart the MCP server. Installed tools retain their extras and version
constraints; change any version pin to allow a newer release. This command
updates installed tools, not environments cached only by `uvx`.

See [uv's tool version and upgrade documentation](https://docs.astral.sh/uv/concepts/tools/).

### Run from a repository checkout

```bash
uv sync --locked --extra mcp
uv run --locked --extra mcp iristool-mcp
```

`iristool-mcp --help` does not require FastMCP. You can use the Python and CLI
APIs without installing MCP support.

### Install the companion skill

The skill provides instructions for agents using the MCP tools. Install the
entire `skills/iristool-data-workflows/` directory through your client's skill
installer or copy it from a local checkout. The destination depends on your
agent. For agents configured to read `~/.agents/skills`, run from the repository
root:

```bash
mkdir -p ~/.agents/skills
cp -R skills/iristool-data-workflows ~/.agents/skills/
```

In Codex, you can download it by asking:

> Use $skill-installer to install skills/iristool-data-workflows from the
> GitHub repository pietrodileo/iristool.

Specify a branch or tag in the request if you want a particular version.
The Codex installer downloads the skill into its skills directory; no manual
repository clone is needed.

After installation, reload your client's skills if needed and ask your agent
to use `iristool-data-workflows`. In Codex, invoke `$iristool-data-workflows`.
If your client has no skill loader, ask the agent to read the
[`SKILL.md`](../skills/iristool-data-workflows/SKILL.md) from your checkout and
follow its instructions for the task. Skill installation is separate from
installing or launching the MCP server.

## Optional extras

Extras add support for specific file formats and dataset providers. Choose the
combination you need when installing:

| Package | Includes |
| --- | --- |
| `iristool[mcp]` | MCP server with CSV, TSV, JSON and JSONL transfers |
| `iristool[mcp,excel]` | MCP server plus XLSX imports and exports |
| `iristool[mcp,huggingface]` | MCP server plus Hugging Face dataset imports |
| `iristool[mcp,kaggle]` | MCP server plus Kaggle dataset imports |
| `iristool[mcp,integrations]` | MCP server plus both dataset providers |
| `iristool[all]` | MCP server, XLSX and both dataset providers |

`all` is the recommended shortcut for `mcp,excel,integrations`. The individual
extras remain available for smaller installations; replace `iristool[all]`
in your client's arguments with the combination you need, keeping its workspace
arguments.

For example, to install MCP support with Excel:

```bash
uv tool install 'iristool[mcp,excel]'
```

If iristool is already installed, replace its installation with the extras you
want to keep:

```bash
uv tool install --force 'iristool[all]'
```

Extras do not change the MCP command or workspace arguments. Provider credentials
belong in each workspace's `.iristool.toml`; installing an extra does not
configure an account.

## Workspace configuration

Copy `.iristool.toml.example` to `.iristool.toml`. The repository gitignores
this filename.

A fleet is the set of named IRIS connections in this file. Each `[instance.NAME]`
defines its own host, SQL port, namespace and credentials. Use a fleet to work
with several IRIS servers or namespaces from one workspace. Instances do not
inherit settings from each other. In this example, `dev` is the default connection
and `reporting` allows read operations only:

```toml
default_server = "dev"

[instance.dev]
host = "localhost"
port = 1972
namespace = "USER"
username = "developer"
password_env = "IRIS_DEV_PASSWORD"

[instance.reporting]
host = "reporting.example.com"
port = 1972
namespace = "REPORTING"
username = "reader"
password_env = "IRIS_REPORTING_PASSWORD"
read_only = true
```

Set the password variables in the environment your MCP process inherits, or use
a literal `password = "..."` instead of `password_env`. Choose exactly one for
each instance, and keep real credentials out of version control. The server does
not load `.env` files or fall back to `_SYSTEM`/`SYS`. It checks every referenced
password when it loads the configuration, including connections you have not used.

Each instance requires `host`, `namespace`, `username` and one password source.
`port` defaults to 1972 and `read_only` to false. With multiple instances, set
`default_server` to one of their names; with one instance, you can omit it.
Unknown settings cause a configuration error.

Pass `server="reporting"` to select that fleet connection in a tool call. If you
omit `server`, the tool uses `default_server`. An unknown name causes an error;
the server does not switch to another instance.

### Changing configuration

The server does not automatically reload `.iristool.toml`. With `--workspace`,
it loads configuration at startup; with workspace discovery, it loads each
workspace's configuration on its first tool call and caches it until shutdown.

After adding or removing a server, changing `read_only`, or editing credentials,
host, namespace or `default_server`, restart the iristool MCP process through
your client. Then call `iris_servers` to verify the loaded settings. Until the
restart, new servers are unavailable and existing settings remain active.

**Setting `read_only = true` in the file does not block writes in an already
running process until it restarts.** Changing it to `false` likewise leaves
writes blocked until restart.

### Read-only connections

Set `read_only = true` on an instance to block database write tools, including
table creation, index creation, and all local-file and provider imports. The
server rejects these calls before opening a connection. You can still list
tables, inspect metadata, and export whole tables or subsets to local files.

This flag controls MCP tools. Use an IRIS account with the appropriate SQL
permissions to enforce access in the database as well.

### Workspace discovery

The server looks for configuration in this order:

1. With `--config NAME`, use that file. A relative name resolves inside the
   selected workspace; an absolute path is used as given. A missing file is an error.
2. Otherwise use the workspace's `.iristool.toml`.
3. If absent, use `~/.iristool.toml`.

Without `--workspace`, the server asks for the client's MCP roots on each tool
call. A single local directory selects the workspace. When the client changes
that root, the next call uses the new workspace. If roots are unsupported or
empty, the server uses its startup directory. If the client advertises roots
but fails to return them, the call fails.

MCP roots do not say which folder is active when a session reports several.
The server rejects that ambiguity. Use a separate MCP session for each workspace,
or select one with `--workspace`. For discovery without arguments, your client
must report one root or start the process in the intended workspace. Without
either, the server has no way to identify the active editor folder.

The server caches configuration and connections separately for each workspace
until shutdown. Several workspace sessions can run at once using the same
installed command. Each file operation uses the workspace selected for that
call without changing the process working directory. Check the workspace in
`iris_servers` or database tool results to confirm the selection. Restart the
server after editing a configuration it has already loaded.

Data paths, including absolute paths and resolved symlinks, must stay inside
the selected workspace. Tools reject TOML files as data inputs or outputs.
Keep credentials out of data files, and gitignore custom fleet configuration
files you keep in a repository.

You can override the workspace or configuration filename when needed. A relative
filename uses the workspace selected by the client or `--workspace`:

```bash
iristool-mcp --config .team-iristool.toml
iristool-mcp --workspace /projects/a --config /home/me/connections.toml
```

The file uses iristool's own configuration format. It does not accept
iris-agentic-dev files or their HTTP `web_port` and `scheme` settings. HTTP TLS
settings do not configure SQL TLS, and the driver connection wrapper has no
TLS configuration option. Check that this SQL connection setup meets your
deployment requirements.

## MCP client configuration

### Cursor

Put this in `.cursor/mcp.json` inside your project:

```json
{
  "mcpServers": {
    "iristool": {
      "command": "uvx",
      "args": [
        "--from", "iristool[all]", "iristool-mcp",
        "--workspace", "${workspaceFolder}"
      ]
    }
  }
}
```

Keep `.iristool.toml` in the project folder alongside `.cursor/`.
Cursor replaces `${workspaceFolder}` with that project's folder when it
starts the server. You do not enter a folder path or select a configuration
in chat. Opening another project launches its server with that project's
folder; separate project windows can use different fleets at the same time.
uvx reuses its cached installation across these launches.

For an installation made with `uv tool install`, use `"command": "iristool-mcp"`
and `"args": ["--workspace", "${workspaceFolder}"]` instead.

After changing the MCP settings, restart the iristool server in Cursor and
ask it to call `iris_servers`. The returned `workspace` should be your project
folder. This setup bypasses MCP-roots discovery, including errors when a client
advertises roots but fails to return them.

See [Cursor's configuration reference](https://prod.cursor.com/docs/mcp) for
project settings and variable interpolation.

### Claude Code

Create `.mcp.json` in the project root alongside `.iristool.toml`:

```json
{
  "mcpServers": {
    "iristool": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "iristool[all]", "iristool-mcp"]
    }
  }
}
```

Start Claude Code from that project folder and approve the project server when
prompted. Claude Code reports the session's launch directory through MCP roots,
so iristool selects its `.iristool.toml` without a path argument. Separate
sessions launched from different projects can use different fleets.

For a persistent installation, set `command` to `iristool-mcp` and remove
`args`. If you use `--add-dir` or `/add-dir`, Claude Code reports multiple roots;
iristool rejects that ambiguity. Use a separate session for each project, or
set `args` to `["--workspace", "/absolute/path/to/project"]` with the installed
command to select one explicitly.

These instructions are for **Claude Code**, not Claude Desktop. A desktop
client without project roots needs an explicit `--workspace` path in its MCP
configuration; it cannot infer the folder from a file mentioned in chat.

See [Claude Code's MCP guide](https://code.claude.com/docs/en/mcp) for project
configuration, approvals and roots behavior.

### Codex

Add this to `.codex/config.toml` in a trusted project, or to
`~/.codex/config.toml` for all projects:

```toml
[mcp_servers.iristool]
command = "uvx"
args = ["--from", "iristool[all]", "iristool-mcp"]
startup_timeout_sec = 60
```

For the CLI, start `codex` from the project folder containing `.iristool.toml`.
The server uses a single reported MCP root when available, otherwise its launch
directory. Check `iris_servers` before importing. Codex loads project-local
configuration only for trusted projects. The longer startup timeout gives uvx
time to install dependencies on the first launch.

Do not use `${workspaceFolder}` in Codex TOML. For a desktop or IDE session
whose roots or launch directory do not identify your project, set an explicit
workspace in that project's configuration:

```toml
[mcp_servers.iristool]
command = "uvx"
args = ["--from", "iristool[all]", "iristool-mcp", "--workspace", "/absolute/path/to/project"]
startup_timeout_sec = 60
```

Replace the example path with your project directory. This fallback binds the
server to that directory; do not put it in global settings if you want one
registration to follow different projects. For a persistent installation, set
`command = "iristool-mcp"` and remove the first three `args` entries, keeping
any `--workspace` pair. Use `/mcp` to inspect the connection and call
`iris_servers` to verify the selected directory.

See the [Codex MCP guide](https://developers.openai.com/codex/mcp) for configuration
scope and the [configuration reference](https://developers.openai.com/codex/config-reference)
for launch settings. These examples do not assume a universal workspace
variable or promise automatic GUI discovery when the client supplies no folder.

### Other clients

Choose one of these configurations in your client's global MCP settings.
These examples use the `mcpServers` JSON format.

With the persistent installation from `uv tool install`:

```json
{
  "mcpServers": {
    "iristool": {
      "command": "iristool-mcp"
    }
  }
}
```

With `uvx`, without a separate iristool installation step:

```json
{
  "mcpServers": {
    "iristool": {
      "command": "uvx",
      "args": ["--from", "iristool[all]", "iristool-mcp"]
    }
  }
}
```

These examples include all optional capabilities. For a smaller installation,
replace `iristool[all]` with a combination such as `iristool[mcp,excel]` or
`iristool[mcp]`.

You can use this registration across workspaces when the client reports one
MCP root per session or starts the command in that workspace. Each workspace
uses its own `.iristool.toml`, configuration cache and database connections,
while sharing the same launch configuration.

If a GUI client does not inherit your shell's PATH, use the command's absolute
path. Supply password variables through the process environment or your client's
secret or environment settings. Registration formats and support for workspace
discovery vary by client.

## Tools

| Tool | Behavior |
| --- | --- |
| `iris_servers` | Names, namespaces, permissions, optional capabilities; no connection opened |
| `iris_tables` | List tables in a schema |
| `iris_describe_table` | Column and index metadata |
| `iris_create_table` | Create from column names and SQL type declarations; never replace |
| `iris_create_index` | Create ordinary, unique, bitmap, bitslice, or columnar indexes |
| `iris_import_file` | CSV/TSV, JSON records, JSONL, XLSX via pandas DataFrames |
| `iris_export_table` | Local CSV/JSON/JSONL in chunks, XLSX in memory |
| `iris_import_huggingface` | Import one HF split using the optional integration |
| `iris_import_kaggle` | Import selected or all CSV/TSV files using the optional integration |

All database tools accept `server` to select a fleet connection. Table tools
also accept `schema`, which defaults to `SQLUser`. The SQL schema is separate
from the IRIS namespace configured on the connection.

As in the Python API, SQL type declarations are supplied by the caller. Use
trusted declarations. The instance's `read_only` flag blocks database writes
before connecting and permits local exports; database account permissions
provide the underlying access control.

The server opens each connection on first use and closes it at shutdown. A
connection stays on one worker thread, so calls to the same instance run in
sequence. Calls to different instances can run concurrently, and pandas or
driver work does not block the MCP event loop.

The server does not retry writes, reconnect or replay operations automatically.
Restart it after losing a connection. Cancelling a client request may leave a
driver call running and does not guarantee a rollback. Check the outcome before
retrying.

The stdio entry point sends Python progress prints from the core and provider
SDKs to stderr. It returns a generic message for unexpected driver or provider
errors to avoid exposing secrets. Tool results report the selected server and
operation time; dataset contents do not pass through the model.

## Imports and performance

To import a file in chunks, pass arguments such as:

```json
{
  "path": "data/people.csv",
  "table": "People",
  "server": "dev",
  "chunk_size": 10000,
  "batch_size": 1000,
  "column_types": {"Number": "BIGINT", "Name": "VARCHAR(255)"}
}
```

Set `chunk_size` to control input memory for CSV, TSV or JSONL. Chunked imports
that create or replace tables require a complete SQL schema. Every chunk must have the same columns in
the same order. Set `batch_size` separately to control how many rows each
`executemany` call submits. Without chunking, the server reads the whole file
and can infer SQL types.

CSV uses nullable pandas dtypes. JSON passes through Python's parser before
pandas to preserve large integers in columns with nulls. Dates remain strings
unless you specify SQL types. Flatten nested records or media into scalar
columns before importing.

All insertion chunks share one transaction, but table creation or replacement
commits first, as in the core library. `replace=true` deletes the old table;
if insertion fails, the replacement can be empty. Provider imports that create
several tables are not atomic.

To add rows to an existing table, call `iris_import_file` with `append=true`:

```json
{
  "path": "random_users.csv",
  "table": "users",
  "schema": "SQLUser",
  "server": "writable",
  "append": true,
  "chunk_size": 10000,
  "batch_size": 1000
}
```

Append preserves existing rows, columns, constraints and indexes. It requires
an existing table and cannot be combined with `replace=true`. The file supplies
the columns to insert; omitted columns use database defaults or nulls where
allowed. IRIS rejects unknown columns, incompatible values, duplicate unique
keys and missing required values. A failed batch rolls back all rows from this
import. Append needs no `column_types`, even with chunking. It is a write
operation and is blocked on read-only connections. Provider import tools do
not support append; download their data to a local file first if needed.

Use `iris_create_index` to add requested secondary indexes after loading.
Creating a unique index can fail on duplicate values without undoing the import.
The Python `df_to_table(indices=...)` API creates indexes before inserting rows.

The Python methods `db.import_file()` and `db.export_table()` share the MCP
transfer functions. Core exports stream by default; custom pandas writer
options load the whole result into a DataFrame.

Exports use 10,000-row chunks by default and preserve large integers in nullable
columns. The writer completes a temporary file in the destination directory,
then atomically moves it into place. To replace a file, set `overwrite=true`.
If the export fails, the previous file survives.

CSV keeps column headers for empty tables. JSON writes an array of row objects;
JSONL writes one object per line. Row order is not guaranteed. XLSX loads the
whole table into pandas and returns `rows=null`.

### Export subsets

Pass `columns`, `filters`, `order_by` and `limit` to `iris_export_table` to
select part of a table. It uses the Python core's query builder and streaming
writer:

```json
{
  "table": "People",
  "path": "adults.jsonl",
  "columns": ["Name", "Age"],
  "filters": [{"column": "Age", "op": ">=", "value": 18}],
  "order_by": [{"column": "Name", "direction": "ASC"}],
  "limit": 100,
  "chunk_size": 10000
}
```

The server combines filters with AND. Supported operators are `=`, `!=`, `<>`,
`<`, `<=`, `>`, `>=`, `IN`, `IS NULL` and `IS NOT NULL`. Use a non-empty list
for `IN`, and omit `value` for NULL operators. Other values must be finite JSON
scalars. The server binds them as parameters rather than treating them as SQL.

Each ordering takes a `column` and an optional `direction`: `ASC` by default,
or `DESC`. The server validates column names against table metadata before
creating output. Omit selection options to export the whole table. `limit`
must be a positive integer. Order by columns with a unique tiebreaker when you
need a limited result to be reproducible.

MCP export selection does not accept raw SQL, expressions, joins, or free-form
WHERE or ORDER BY clauses. You can export subsets from read-only fleet entries,
subject to database account permissions. Python callers can use
`db.export_query()` for parameterized SQL; that API does not enforce read-only
statements. CSV, JSON and JSONL stream the selected result. XLSX loads it into
memory.

### Dataset imports and credentials

Hugging Face imports load a complete split. Use a slice such as
`split="train[:10000]"` to limit it. Kaggle imports load one complete CSV or TSV
at a time; select a `file` to limit downloads.

Set provider credentials in the workspace's `.iristool.toml`, alongside its
IRIS fleet:

```toml
[providers.huggingface]
token = "hf_your_token"

[providers.kaggle]
token = "your_kaggle_api_token"
```

You can use `token_env = "WORKSPACE_SPECIFIC_VARIABLE"` instead of `token` in
either section. Choose exactly one. Configuration representations and tool
results hide the tokens. Keep the file out of version control.

Without a Hugging Face section, MCP uses anonymous access. Kaggle imports
require a configured token even for public datasets. MCP does not use the
machine's saved provider login.

Kaggle's SDK stores credentials globally, so the server runs each download in
an isolated subprocess. Concurrent workspaces can use different accounts without
changing the parent process environment or login. The server caches each
workspace's configuration until restart. Standalone Python and CLI integrations
use the SDK login defaults when you supply no token. These tools do not upload
or publish datasets.

The [benchmarks](mcp-benchmarks.md) compare memory use and timing and include
commands to reproduce the measurements. They support lower memory use for the
tested workload; the timing differences are too small to claim a general speed
improvement. Results from local IRIS and the generated data do not establish
performance for remote servers, concurrent workloads or other file formats.

## Companion skill

The optional
[`iristool-data-workflows` skill](../skills/iristool-data-workflows/SKILL.md)
guides agents through connection selection, imports, validation, indexing and
exports.

Follow [Install the companion skill](#install-the-companion-skill) for download
and local installation options.

To install from a local checkout instead, copy its entire directory into your
agent's skills directory, such as
`~/.agents/skills/iristool-data-workflows/`, then ask the agent to use
`iristool-data-workflows` for the task. The README has installation steps and an
example request.

Installing the Python package does not install the skill. The skill provides
workflow instructions; the server enforces permissions and validates file paths.

## Uninstall

Remove the `iristool` entry from your client's MCP settings, then stop its
running MCP session or restart the client.

If you installed with `uv tool install`, remove the installed command and its
environment:

```bash
uv tool uninstall iristool
```

If you used `uvx`, there is no persistent tool installation to uninstall.
Removing the MCP entry stops the client from launching it. To also remove
cached entries associated with the package, run:

```bash
uv cache clean iristool
```

This package-specific cleanup does not remove every dependency from uv's cache.

To remove the companion skill, use your agent's skill manager or delete only
the `iristool-data-workflows` directory from the location where you installed
it. Reload the agent's skills or restart its session if needed.

Uninstalling leaves workspace `.iristool.toml` files, imported IRIS tables and
exported files in place. Remove those separately if you no longer need them.

## Validation and distribution

```bash
uv run --locked --all-extras python -m unittest discover -s tests -v -b
IRIS_INTEGRATION=1 uv run --locked --all-extras python -m unittest discover -s tests -v -b
```

Live tests create uniquely named tables and remove them afterwards. Live
provider tests require the separate opt-in variables listed in the README.

Publish iristool to PyPI through the package's release workflow. The MCP server
ships in the same package, so it needs no separate package or binary hosting.
An MCP Registry entry can point to the published package.

### Test a two-instance fleet

The separate fleet Compose file starts two containers from the same project
image. It has no volume mounts or durable-storage configuration. Each container
keeps its own data in its writable layer; removing the container removes that
data. The original `docker-compose.yml` setup is independent.

```bash
docker compose -f docker-compose.fleet.yml build writable
docker compose -f docker-compose.fleet.yml up -d --no-build
docker compose -f docker-compose.fleet.yml logs -f
```

Wait until both services report that IRIS has started, then stop following the
logs with Ctrl+C. Run the tests from another terminal or after leaving the logs:

```bash
IRIS_FLEET_INTEGRATION=1 uv run --locked --all-extras python -m unittest discover -s tests -p test_fleet_integration.py -v -b
```

The writable instance uses SQL port 9191 and portal port 9192. The read-only
instance uses SQL port 9291 and portal port 9292. All ports bind to localhost.
These are disposable development instances using the image's `_SYSTEM` / `SYS`
administrator login. If you changed that password, set
`IRIS_FLEET_ADMIN_PASSWORD` when running the tests.

To use these containers from your MCP client, copy the
[Docker fleet configuration](../.iristool.fleet.toml.example) into your workspace:

```bash
cp .iristool.fleet.toml.example .iristool.toml
```

If `.iristool.toml` already exists, merge the example's two instance sections
and `default_server` setting instead of overwriting your configuration. Restart
the MCP server and call `iris_servers`: it should list `writable` (default,
port 9191) and `readonly` (port 9291). The example uses the local image's default
credentials; update them if yours differ. Its `read_only=true` setting blocks
MCP write tools, while the `_SYSTEM` account retains database write access.
Use a restricted SQL account to enforce read-only access in IRIS as well.

The tests create temporary SQL accounts and tables, plus a workspace TOML fleet
configuration discovered through MCP workspace roots. The reader receives only
`SELECT` on the test table. The writer receives table creation, index creation
and data modification privileges. Tests check concurrent reads and exports from
both instances, default and explicit routing, successful imports and indexing,
and rejection of all MCP write tools on the read-only connection. They also
disable the MCP read-only setting and verify that IRIS still denies table
creation and direct `INSERT`, `UPDATE` and `DELETE` for the reader. Provider
downloads are not performed. Temporary accounts and tables are removed afterwards.

Stop the fleet while keeping the containers, or remove them and their data:

```bash
docker compose -f docker-compose.fleet.yml stop
docker compose -f docker-compose.fleet.yml down
```

