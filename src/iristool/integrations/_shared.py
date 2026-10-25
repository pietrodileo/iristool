"""Shared name handling; SQL inference and writes belong to IRIStool."""

import re


def _raise_if_access_denied(exc, url, token):
    """SDKs may wrap HTTP access errors; preserve unrelated failures."""
    cause = exc
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        status = getattr(getattr(cause, "response", None), "status_code", None)
        kind = type(cause).__name__
        # datasets can re-raise DatasetNotFoundError from None, losing the HTTP cause.
        gated = kind == "DatasetNotFoundError" and "is a gated dataset" in str(cause)
        if status in (401, 403) or kind in {"GatedRepoError", "UnauthenticatedError"} or gated:
            raise PermissionError(
                f"Dataset processing failed: access denied. Open {url} in your browser, "
                "sign in and confirm the terms or request access. Wait for approval if required. "
                f"Then set {token} (or log in with the source SDK) using the approved account "
                "and repeat the same command. No dataset tables were imported."
            ) from exc
        cause = cause.__cause__ or cause.__context__


def _name(value):
    name = re.sub(r"[^A-Za-z0-9_]", "_", str(value).strip())
    return name if re.match(r"[A-Za-z]", name) else "Data_" + name


def _validate_target(table, schema):
    if table is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", table):
        raise ValueError("table must start with a letter and contain letters, digits or underscores.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", schema):
        raise ValueError("schema must start with a letter and contain letters, digits or underscores.")


def _import_frames(db, frames, schema, replace):
    result = {}
    for label, frame, name in frames:
        frame.columns = [_name(column) for column in frame.columns]
        if len({column.casefold() for column in frame.columns}) != len(frame.columns):
            raise ValueError(f"Column names collide after normalization in {label}.")
        db.df_to_table(frame, name, table_schema=schema,
                       exist_ok=replace, drop_if_exists=replace)
        result[f"{schema}.{name}"] = len(frame)
        print(f"{label} -> {schema}.{name}: {len(frame)} rows")
    return result
