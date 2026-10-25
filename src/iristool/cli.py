"""Core command-line tools; credentials come from IRIS_* environment variables."""

import argparse
import os

from iristool import IRIStool


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
    args = parser.parse_args()
    try:
        with _connection() as db:
            path = db.export_table(args.table, args.output, table_schema=args.schema,
                                   overwrite=args.overwrite)
    except Exception as exc:
        parser.exit(1, f"Export failed: {exc}\n")
    print(f"Exported to {path}")
