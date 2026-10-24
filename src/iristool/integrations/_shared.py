"""Shared name handling; SQL inference and writes belong to IRIStool."""

import re


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
