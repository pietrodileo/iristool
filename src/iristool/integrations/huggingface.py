"""Hugging Face downloads and converts to pandas; iristool writes to IRIS."""

import re
from urllib.parse import urlsplit

from pandas.api.types import is_object_dtype, is_scalar

from ._shared import _import_frames, _name, _validate_target, _raise_if_access_denied


def import_dataset(db, dataset, *, split="train", config=None, revision=None,
                   table=None, schema="SQLUser", replace=False, token=None):
    """Load one Hugging Face split into IRIS; return {qualified_table: row_count}.

    Authentication uses HF_TOKEN or the Hugging Face login cache. Pass token explicitly (False disables saved credentials). Connection
    ownership stays with the caller; db must be an open IRIStool connection.
    """
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise ImportError('Install Hugging Face support with: pip install "iristool[huggingface]"') from exc
    if dataset.startswith("https://"):
        url = urlsplit(dataset)
        if url.netloc != "huggingface.co" or not url.path.startswith("/datasets/"):
            raise ValueError("Use a Hugging Face dataset URL or repository ID.")
        dataset = url.path.removeprefix("/datasets/").rstrip("/")
    if (not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)?", dataset)
            or not isinstance(split, str) or not split.strip()):
        raise ValueError("Use a Hugging Face repository ID and a non-empty split name.")
    _validate_target(table, schema)
    name = table or _name("HF_" + "_".join(filter(None, [dataset.split("/")[-1], config, split])))
    try:
        frame = load_dataset(dataset, name=config, split=split, revision=revision,
                             **({"token": token} if token is not None else {})).to_pandas()
    except Exception as exc:
        _raise_if_access_denied(exc, f"https://huggingface.co/datasets/{dataset}", "HF_TOKEN")
        raise
    for column, values in frame.items():
        if is_object_dtype(values.dtype) and not values.map(is_scalar).all():
            raise ValueError(f"Column {column!r} contains nested or media values. "
                             "Flatten or serialize these values before importing with iristool.")
    return _import_frames(db, [(f"{dataset} [{split}]", frame, name)], schema, replace)

