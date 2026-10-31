"""Optional stdio MCP entry point. Install with iristool[mcp]."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import importlib.util
import io
import logging
from pathlib import Path
import sys
from time import perf_counter
from urllib.parse import urlsplit
from urllib.request import url2pathname

from iristool import IRIStool


class _ProtocolStdout(io.TextIOBase):
    """MCP wraps .buffer; ordinary Python prints go to stderr process-wide."""

    def __init__(self, protocol, diagnostics):
        self.buffer = protocol.buffer
        self.diagnostics = diagnostics

    def write(self, text):
        return self.diagnostics.write(text)

    def flush(self):
        return self.diagnostics.flush()


class Fleet:
    """One lazy, thread-confined connection per configured server."""

    def __init__(self, config, factory=IRIStool):
        self.config = config
        self.factory = factory
        self.workers = {}
        self.connections = {}

    async def call(self, server, write, operation):
        from fastmcp.exceptions import ToolError

        name = self.config.default_server if server is None else server
        if name not in self.config.connections:
            raise ToolError("Unknown server; call iris_servers to list configured names.")
        settings = self.config.connections[name]
        if write and settings.read_only:
            raise ToolError(f"Server {name!r} is configured read-only.")
        worker = self.workers.get(name)
        if worker is None:
            worker = self.workers[name] = ThreadPoolExecutor(max_workers=1)

        def run():
            try:
                if name not in self.connections:
                    self.connections[name] = self.factory(**settings.arguments())
                start = perf_counter()
                result = operation(self.connections[name])
                return {"server": name, "workspace": str(self.config.workspace),
                        "elapsed_seconds": round(perf_counter() - start, 4),
                        **result}
            except Exception as exc:
                # Driver/provider exceptions can include credentials or request URLs.
                if isinstance(exc, (ValueError, FileExistsError, FileNotFoundError, ImportError)):
                    message = str(exc)
                    for connection in self.config.connections.values():
                        message = message.replace(connection.password, "[redacted]")
                    for token in (self.config.huggingface_token, self.config.kaggle_token):
                        if token:
                            message = message.replace(token, "[redacted]")
                else:
                    message = f"{type(exc).__name__}: operation failed; verify input, permissions and connectivity."
                raise ToolError(message) from None

        return await asyncio.get_running_loop().run_in_executor(worker, run)

    async def close(self):
        loop = asyncio.get_running_loop()
        for name, worker in self.workers.items():
            def close(name=name):
                connection = self.connections.pop(name, None)
                if connection is not None:
                    connection.close()
            try:
                await loop.run_in_executor(worker, close)
            except Exception as exc:
                logging.warning("Failed to close IRIS connection %r (%s)", name, type(exc).__name__)
            finally:
                worker.shutdown(wait=True)


async def _client_workspace(fallback):
    from fastmcp.server.dependencies import get_context
    from fastmcp.exceptions import ToolError

    ctx = get_context()
    params = ctx.session.client_params
    if params is None or params.capabilities.roots is None:
        return fallback
    try:
        roots = await ctx.list_roots()
    except Exception:
        raise ToolError("Unable to read client workspace roots; no configuration was selected.") from None
    if not roots:
        return fallback
    paths = set()
    for root in roots:
        uri = urlsplit(str(root.uri))
        if (uri.scheme != "file" or uri.netloc not in ("", "localhost")
                or uri.query or uri.fragment):
            raise ToolError("Workspace roots must be local file URIs.")
        path = Path(url2pathname(uri.path))
        if not path.is_absolute():
            raise ToolError("Workspace roots must be absolute directories.")
        paths.add(path.resolve())
    if len(paths) != 1:
        raise ToolError("Client reports multiple workspace roots with no active-folder signal. "
                        "Use a separate MCP session per workspace or an explicit --workspace.")
    return paths.pop()


def create_server(config=None, *, factory=IRIStool, workspace=None, filename=None):
    from fastmcp import FastMCP
    from pydantic import Field
    from typing import Annotated
    from fastmcp.exceptions import ToolError
    from iristool.mcp_config import load_config
    from iristool.transfer import import_file, export_file

    fixed_config = config if config is not None else (
        load_config(workspace, filename) if workspace is not None else None)
    fallback = Path.cwd().resolve()
    fleets = {}

    async def resolve():
        if fixed_config is not None:
            key = fixed_config.workspace
            if key not in fleets:
                fleets[key] = Fleet(fixed_config, factory)
        else:
            key = await _client_workspace(fallback)
            if key not in fleets:
                try:
                    selected = load_config(key, filename)
                except (ValueError, OSError) as exc:
                    raise ToolError(f"Invalid workspace configuration ({type(exc).__name__}); "
                                    "check .iristool.toml and password environment variables.") from None
                fleets[key] = Fleet(selected, factory)
        fleet = fleets[key]
        return fleet, fleet.config

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            for fleet in fleets.values():
                await fleet.close()

    mcp = FastMCP("iristool", lifespan=lifespan, mask_error_details=True,
                  instructions="Use iris_servers to select a connection. File paths are relative "
                  "to the configured workspace. Replacement deletes the existing table. "
                  "Imports commit DDL before insertion; failed replacement may leave an empty table.")

    @mcp.tool(annotations={"readOnlyHint": True})
    async def iris_servers() -> dict:
        """List fleet connections and installed optional capabilities, without passwords."""
        fleet, config = await resolve()
        return {"workspace": str(config.workspace), "default_server": config.default_server,
                "servers": [{"server": name, "host": c.host, "port": c.port,
                             "namespace": c.namespace, "read_only": c.read_only}
                            for name, c in config.connections.items()],
                "capabilities": {name: importlib.util.find_spec(module) is not None
                                 for name, module in (("excel", "openpyxl"),
                                                      ("huggingface", "datasets"),
                                                      ("kaggle", "kagglehub"))}}

    @mcp.tool(annotations={"readOnlyHint": True})
    async def iris_tables(server: str | None = None, schema: str = "SQLUser") -> dict:
        """List tables in a SQL schema on the selected server."""
        fleet, config = await resolve()
        def operation(db):
            db._identifier(schema)
            return {"tables": db.show_namespace_tables(table_schema=schema).to_dict(orient="records")}
        return await fleet.call(server, False, operation)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def iris_describe_table(table: str, server: str | None = None,
                                  schema: str = "SQLUser") -> dict:
        """Describe a table's columns and indexes. Pass the schema separately."""
        fleet, config = await resolve()
        return await fleet.call(server, False, lambda db: {"metadata": db.describe_table(table, schema)})

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    async def iris_create_table(table: str, columns: dict[str, str],
                               server: str | None = None, schema: str = "SQLUser") -> dict:
        """Create a new table from column names and SQL type declarations; existing tables fail."""
        fleet, config = await resolve()
        def operation(db):
            if not columns:
                raise ValueError("Provide at least one column.")
            db.create_table(table, columns, table_schema=schema, check_exists=True)
            return {"table": f"{schema}.{table}", "created": True}
        return await fleet.call(server, True, operation)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    async def iris_create_index(table: str, column: str, index: str,
                               index_type: str = "index", server: str | None = None,
                               schema: str = "SQLUser") -> dict:
        """Create an ordinary, unique, bitmap, bitslice or columnar index after loading data."""
        fleet, config = await resolve()
        def operation(db):
            db.create_index(index, table, column, index_type=index_type, table_schema=schema)
            return {"table": f"{schema}.{table}", "index": index, "created": True}
        return await fleet.call(server, True, operation)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    async def iris_import_file(path: str, table: str, server: str | None = None,
                               schema: str = "SQLUser", replace: bool = False,
                               column_types: dict[str, str] | None = None,
                               batch_size: int = 1000, chunk_size: int | None = None,
                               separator: str | None = None, sheet_name: str | int = 0) -> dict:
        """Import workspace CSV/TSV, JSON records, JSONL or XLSX using pandas.

        chunk_size enables bounded-memory CSV/TSV/JSONL reads and requires complete
        column_types. Omit it for automatic type inference on a whole DataFrame.
        replace=True deletes the previous table; replacement is not atomic.
        """
        fleet, config = await resolve()
        def operation(db):
            count = import_file(db, config.local_path(path), table, schema=schema,
                                replace=replace, column_types=column_types,
                                batch_size=batch_size, chunk_size=chunk_size,
                                separator=separator, sheet_name=sheet_name)
            return {"table": f"{schema}.{table}", "rows": count,
                    "warnings": ["Replacement commits before insertion; failures may leave an empty table."]
                    if replace else []}
        return await fleet.call(server, True, operation)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    async def iris_export_table(table: str, path: str, server: str | None = None,
                                schema: str = "SQLUser", overwrite: bool = False,
                                chunk_size: int = 10000, columns: list[str] | None = None,
                                filters: list[dict] | None = None,
                                order_by: list[dict] | None = None,
                                limit: Annotated[int, Field(strict=True, gt=0)] | None = None) -> dict:
        """Export to workspace CSV/JSON/JSONL in chunks, or XLSX in memory.

        Does not modify IRIS, so allowed on read-only servers. Existing files
        require overwrite=True. The previous output survives a failed export.
        Select columns; filters are ANDed {column, op, value} objects. Allowed op:
        =, !=, <>, <, <=, >, >=, IN (list value), IS NULL/IS NOT NULL (omit value).
        order_by is [{column, direction: ASC|DESC}]. limit is a positive integer.
        Values are bound; no SQL expressions accepted. Order explicitly for
        reproducible limited results. XLSX returns rows=null.
        """
        fleet, config = await resolve()
        def operation(db):
            result = export_file(db, table, config.local_path(path), schema=schema,
                                 overwrite=overwrite, chunk_size=chunk_size, columns=columns,
                                 filters=filters, order_by=order_by, limit=limit)
            result["warnings"] = ["XLSX export loads the whole table into memory."] if path.lower().endswith(".xlsx") else []
            return result
        return await fleet.call(server, False, operation)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
    async def iris_import_huggingface(dataset: str, server: str | None = None,
                                      table: str | None = None, schema: str = "SQLUser",
                                      split: str = "train", config_name: str | None = None,
                                      revision: str | None = None, replace: bool = False) -> dict:
        """Download an HF split and import scalar columns. Loads the split into memory.

        Configure providers.huggingface in workspace TOML for gated/private data. Pin revision for reproducibility.
        replace=True deletes previous target data; replacement is not atomic.
        """
        fleet, config = await resolve()
        from iristool.integrations import import_huggingface
        return await fleet.call(server, True, lambda db: {
            "tables": import_huggingface(db, dataset, table=table, schema=schema,
                                         split=split, config=config_name, revision=revision,
                                         replace=replace, token=config.huggingface_token or False)})

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
    async def iris_import_kaggle(dataset: str, server: str | None = None,
                                file: str | None = None, table: str | None = None,
                                schema: str = "SQLUser", replace: bool = False) -> dict:
        """Download Kaggle CSV/TSV files and import them, one DataFrame per file.

        Configure providers.kaggle.token or token_env in workspace TOML. Select file to avoid downloading all
        files. Multiple tables are not atomic; replace=True deletes target data.
        """
        fleet, config = await resolve()
        if config.kaggle_token is None:
            raise ToolError("Configure [providers.kaggle] with token or token_env in .iristool.toml.")
        from iristool.integrations import import_kaggle
        return await fleet.call(server, True, lambda db: {
            "tables": import_kaggle(db, dataset, file=file, table=table, schema=schema,
                                    replace=replace, token=config.kaggle_token)})

    return mcp


def main():
    parser = argparse.ArgumentParser(description="Run the iristool stdio MCP server (requires iristool[mcp]).")
    parser.add_argument("--workspace", help="Override automatic MCP workspace discovery (client roots, then process working directory)")
    parser.add_argument("--config", help="TOML filename; defaults to workspace then home .iristool.toml")
    args = parser.parse_args()
    try:
        server = create_server(workspace=args.workspace, filename=args.config)
    except ImportError:
        parser.exit(1, 'Install MCP support with: uv tool install "iristool[mcp]"\n')
    except (ValueError, OSError) as exc:
        # TOML parser errors can contain source snippets, including credentials.
        parser.exit(1, f"Invalid MCP configuration ({type(exc).__name__}); check file, instance settings and password environment variables.\n")
    # Providers may print progress; protocol output must be the only stdout.
    protocol_output = sys.stdout
    sys.stdout = _ProtocolStdout(protocol_output, sys.stderr)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        server.run(transport="stdio", show_banner=False, log_level="WARNING")
    finally:
        sys.stdout = protocol_output


if __name__ == "__main__":
    main()
