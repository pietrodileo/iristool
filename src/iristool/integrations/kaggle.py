"""Download Kaggle CSV/TSV files and import them through an existing IRIStool."""

from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

import pandas as pd

from ._shared import _import_frames, _name, _validate_target


def _handle(dataset):
    if dataset.startswith("https://"):
        url = urlsplit(dataset)
        if url.netloc not in {"kaggle.com", "www.kaggle.com"} or not url.path.startswith("/datasets/"):
            raise ValueError("Use a Kaggle dataset URL or owner/dataset handle.")
        dataset = url.path.removeprefix("/datasets/")
    dataset = dataset.rstrip("/")
    if not re.fullmatch(r"[\w-]+/[\w-]+(?:/versions/[1-9][0-9]*)?", dataset, re.ASCII):
        raise ValueError("Use owner/dataset, optionally followed by /versions/NUMBER.")
    return dataset


def import_dataset(db, dataset, *, file=None, table=None, schema="SQLUser", replace=False,
                   read_csv_kwargs=None):
    """Import CSV/TSV files; return {qualified_table: row_count}.

    db is an open IRIStool connection. read_csv_kwargs goes directly to pandas
    (e.g. dtype, sep, encoding, parse_dates). The caller owns the connection.
    Existing tables fail unless replace=True, which deletes their previous data.
    """
    try:
        import kagglehub
    except ImportError as exc:
        raise ImportError('Install Kaggle support with: pip install "iristool[kaggle]"') from exc
    dataset = _handle(dataset)
    if file is not None:
        path = PurePosixPath(file)
        if not file or path.is_absolute() or ".." in path.parts or "\\" in file:
            raise ValueError("file must be a relative path within the dataset.")
        if path.suffix.lower() not in {".csv", ".tsv"}:
            raise ValueError("Only CSV and TSV files are supported.")
    _validate_target(table, schema)

    downloaded = Path(kagglehub.dataset_download(dataset, **({"path": file} if file else {})))
    files = [downloaded] if downloaded.is_file() else sorted(
        p for p in downloaded.rglob("*") if p.is_file() and p.suffix.lower() in {".csv", ".tsv"}
    )
    if not files:
        raise ValueError("No CSV/TSV files found in this dataset.")
    if table is not None and len(files) != 1:
        raise ValueError("--table requires a single file; select one with --file.")
    names = [table or _name(p.stem) for p in files]
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("File names produce duplicate table names; use --file and --table.")

    frames = (
        (path.name, pd.read_csv(path, **{
                "sep": "\t" if path.suffix.lower() == ".tsv" else ",",
                **(read_csv_kwargs or {}),
            }), name)
        for path, name in zip(files, names)
    )
    return _import_frames(db, frames, schema, replace)

