"""Core command-line tools; credentials come from IRIS_* environment variables."""

import argparse
import json
import os

from iristool import IRIStool


def main_globals():
    from .globals import FORMATS, export_globals, import_globals, resolve_global
    parser = argparse.ArgumentParser(description="Transfer native IRIS global files")
    commands = parser.add_subparsers(dest="command", required=True)
    locate = commands.add_parser("resolve")
    locate.add_argument("name")
    locate.add_argument("--subscript", default="")
    export = commands.add_parser("export")
    export.add_argument("path")
    export.add_argument("names", nargs="+")
    export.add_argument("--format", choices=FORMATS, default="auto")
    export.add_argument("--translation", default="")
    load = commands.add_parser("import")
    load.add_argument("path")
    load.add_argument("--names", nargs="+")
    load.add_argument("--format", choices=[f for f in FORMATS if f != "auto"], default="ism")
    for command in (export, load):
        command.add_argument("--records", choices=["V", "S"], default="V")
        command.add_argument("--server-file", action="store_true", help="Path on the IRIS host")
    args = parser.parse_args()
    try:
        with _connection() as db:
            if args.command == "resolve":
                result = resolve_global(db, args.name, args.subscript)
            elif args.command == "export":
                result = export_globals(db, args.names, args.path, output_format=args.format,
                                        records=args.records, translation=args.translation,
                                        server_file=args.server_file)
            else:
                result = import_globals(db, args.path, names=args.names, input_format=args.format,
                                        records=args.records, server_file=args.server_file)
    except Exception as exc:
        parser.exit(1, f"Global {args.command} failed: {exc}\n")
    print(json.dumps(result))


def _connection(default_port=1972, **overrides):
    settings = {
        "host": os.getenv("IRIS_HOST", "localhost"),
        "port": os.getenv("IRIS_PORT", str(default_port)),
        "namespace": os.getenv("IRIS_NAMESPACE", "USER"),
        "username": os.getenv("IRIS_USER", "_SYSTEM"),
        "password": os.getenv("IRIS_PASSWORD", "SYS"),
    }
    settings.update(overrides)
    return IRIStool(**settings)


def main_export():
    parser = argparse.ArgumentParser(description="Export an IRIS table to CSV, XLSX or JSON using iristool.")
    parser.add_argument("table", help="Table name without schema")
    parser.add_argument("output", help="Output file ending in .csv, .xlsx or .json")
    parser.add_argument("--schema", default="SQLUser", help="SQL schema (default: SQLUser)")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output file")
    parser.add_argument("--sheet-name", help="XLSX sheet name (default: Sheet1)")
    parser.add_argument("--append", action="store_true", help="Keep other XLSX sheets; --overwrite replaces only the selected sheet")
    args = parser.parse_args()
    try:
        with _connection() as db:
            path = db.export_table(args.table, args.output, table_schema=args.schema,
                                   overwrite=args.overwrite, sheet_name=args.sheet_name,
                                   append=args.append)
    except Exception as exc:
        parser.exit(1, f"Export failed: {exc}\n")
    print(f"Exported to {path}")
