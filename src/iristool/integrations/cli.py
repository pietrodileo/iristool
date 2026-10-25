"""One-command imports; credentials come from IRIS_* environment variables."""

import argparse
from iristool.cli import _connection
from . import import_kaggle, import_huggingface


def _run(parser, importer, default_port):
    args = parser.parse_args()
    try:
        with _connection(default_port) as db:
            importer(db, **vars(args))
    except Exception as exc:
        parser.exit(1, f"Import failed: {exc}\n")


def main_kaggle(default_port=1972):
    parser = argparse.ArgumentParser(description="Load Kaggle CSV/TSV datasets into IRIS using iristool.")
    parser.add_argument("dataset", help="owner/dataset or https://www.kaggle.com/datasets/owner/dataset")
    parser.add_argument("--file", help="Import only this relative file path")
    parser.add_argument("--table", help="Table name (single-file import only)")
    parser.add_argument("--schema", default="SQLUser", help="SQL schema (default: SQLUser)")
    parser.add_argument("--replace", action="store_true", help="Delete and recreate an existing target table")
    _run(parser, import_kaggle, default_port)


def main_huggingface(default_port=1972):
    parser = argparse.ArgumentParser(description="Load a Hugging Face dataset split into IRIS using iristool.")
    parser.add_argument("dataset", help="Repository ID or https://huggingface.co/datasets/owner/dataset")
    parser.add_argument("--split", default="train", help="Split or slice, e.g. train[:100] (default: train)")
    parser.add_argument("--config", help="Dataset configuration/subset")
    parser.add_argument("--revision", help="Dataset branch, tag or commit")
    parser.add_argument("--table", help="Table name (default: HF_<dataset>_[<config>_]<split>)")
    parser.add_argument("--schema", default="SQLUser", help="SQL schema (default: SQLUser)")
    parser.add_argument("--replace", action="store_true", help="Delete and recreate an existing target table")
    _run(parser, import_huggingface, default_port)


