"""Shared core and MCP pandas transfers with bounded-memory file operations."""

from itertools import islice
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile

import pandas as pd


def _json_frame(records):
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise ValueError("JSON input must contain row objects (a records array or JSONL).")
    frame = pd.DataFrame(records, dtype=object)
    for column in frame:
        values = frame[column].dropna().tolist()
        if values and all(type(v) is int for v in values):
            if min(values) >= -(2**63) and max(values) < 2**63:
                frame[column] = pd.array(frame[column], dtype="Int64")
        elif values and all(type(v) is bool for v in values):
            frame[column] = pd.array(frame[column], dtype="boolean")
        elif values and all(type(v) in (int, float) for v in values):
            if any(type(v) is int and abs(v) > 2**53 for v in values):
                raise ValueError("Mixed integer/float JSON columns with large integers require preprocessing to preserve precision.")
            frame[column] = pd.array(frame[column], dtype="Float64")
    return frame


def _jsonl_frames(path, chunk_size):
    with path.open(encoding="utf-8") as source:
        rows = (json.loads(line) for line in source if line.strip())
        while records := list(islice(rows, chunk_size)):
            yield _json_frame(records)


def _positive(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer.")


def import_file(db, path, table, *, schema="SQLUser", replace=False,
                column_types=None, batch_size=1000, chunk_size=None,
                separator=None, sheet_name=0):
    """Import CSV/TSV, JSON records/JSONL or XLSX; return the inserted row count.

    Streaming CSV/JSONL requires a complete explicit SQL schema. All insertion
    chunks share one transaction. Table creation/replacement commits first,
    matching df_to_table: a failed load may leave an empty newly created table.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    _positive(batch_size, "batch_size")
    db.validate_table_name(table, schema)
    if chunk_size is not None:
        _positive(chunk_size, "chunk_size")
        if suffix not in {".csv", ".tsv", ".jsonl"} or not column_types:
            raise ValueError("Streaming imports require CSV/TSV/JSONL and complete column_types.")
    if suffix in {".csv", ".tsv"}:
        frames = pd.read_csv(path, sep=separator or ("\t" if suffix == ".tsv" else ","),
                             dtype_backend="numpy_nullable", chunksize=chunk_size)
    elif suffix == ".jsonl":
        if chunk_size is not None:
            frames = _jsonl_frames(path, chunk_size)
        else:
            with path.open(encoding="utf-8") as source:
                frames = _json_frame([json.loads(line) for line in source if line.strip()])
    elif suffix == ".json":
        with path.open(encoding="utf-8") as source:
            frames = _json_frame(json.load(source))
    elif suffix == ".xlsx":
        frames = pd.read_excel(path, sheet_name=sheet_name, dtype_backend="numpy_nullable")
    else:
        raise ValueError("Choose a CSV, TSV, JSON, JSONL or XLSX input file.")
    if chunk_size is None:
        db.df_to_table(frames, table, table_schema=schema, column_types=column_types,
                       exist_ok=replace, drop_if_exists=replace, batch_size=batch_size)
        return len(frames)
    count = 0
    columns = None
    try:
        with closing(frames), db.conn.cursor() as cursor:
            for frame in frames:
                names = db._column_names(frame.columns)
                if columns is None:
                    columns = names
                    db.df_to_table(frame.iloc[:0], table, table_schema=schema,
                                   column_types=column_types, exist_ok=replace,
                                   drop_if_exists=replace, batch_size=batch_size)
                    sql = (f"INSERT INTO {db.validate_table_name(table, schema)} "
                           f"({', '.join(db._identifier(c) for c in columns)}) "
                           f"VALUES ({', '.join('?' for _ in columns)})")
                elif names != columns:
                    raise ValueError("Columns changed between input chunks.")
                rows = (tuple(db._sql_value(v) for v in row)
                        for row in frame.itertuples(index=False, name=None))
                while batch := list(islice(rows, batch_size)):
                    db._execute_batch(cursor, sql, batch)
                    count += len(batch)
            if columns is None:
                raise ValueError("Input contains no columns; no table was created.")
            db.conn.commit()
    except BaseException:
        db.conn.rollback()
        raise
    return count


def table_query(db, table, *, schema="SQLUser", columns=None, filters=None,
                order_by=None, limit=None):
    """Build a SELECT from identifiers and bound scalar values, never SQL fragments."""
    db.validate_table_name(table, schema)
    qualified = f"{db._identifier(schema)}.{db._identifier(table)}"
    if limit is not None:
        _positive(limit, "limit")
    names = []
    def identifier(name):
        quoted = db._identifier(name)
        names.append(name)
        return quoted

    projection = "*"
    if columns is not None:
        if not isinstance(columns, list) or not columns:
            raise ValueError("columns must be a non-empty list of column names.")
        projection = ", ".join(identifier(name) for name in columns)
        if len({name.casefold() for name in columns}) != len(columns):
            raise ValueError("columns must not contain duplicates.")
    if filters is not None and not isinstance(filters, list):
        raise ValueError("filters must be a list of conditions combined with AND.")
    clauses, parameters = [], []
    def scalar(value):
        import math
        if type(value) not in (str, int, float, bool) or (type(value) is float and not math.isfinite(value)):
            raise ValueError("Filter values must be finite JSON scalars; use IS NULL for nulls.")
        return value

    for condition in filters or []:
        if not isinstance(condition, dict) or set(condition) - {"column", "op", "value"}:
            raise ValueError("Each filter accepts column, op and optionally value.")
        column = identifier(condition.get("column"))
        operator = condition.get("op")
        if not isinstance(operator, str):
            raise ValueError("Each filter requires an allowed op.")
        operator = operator.upper()
        if operator in {"IS NULL", "IS NOT NULL"}:
            if "value" in condition:
                raise ValueError("NULL operators do not accept value.")
            clauses.append(f"{column} {operator}")
        elif operator == "IN":
            values = condition.get("value")
            if not isinstance(values, list) or not values:
                raise ValueError("IN requires a non-empty list of scalar values.")
            parameters.extend(scalar(value) for value in values)
            clauses.append(f"{column} IN ({', '.join('?' for _ in values)})")
        elif operator in {"=", "!=", "<>", "<", "<=", ">", ">="}:
            parameters.append(scalar(condition.get("value")))
            clauses.append(f"{column} {operator} ?")
        else:
            raise ValueError("Unsupported filter operator.")
    if order_by is not None and not isinstance(order_by, list):
        raise ValueError("order_by must be a list of column/direction objects.")
    ordering = []
    for item in order_by or []:
        if not isinstance(item, dict) or set(item) - {"column", "direction"}:
            raise ValueError("Each ordering accepts column and direction.")
        column = identifier(item.get("column"))
        direction = item.get("direction", "ASC")
        if not isinstance(direction, str) or direction.upper() not in {"ASC", "DESC"}:
            raise ValueError("Ordering direction must be ASC or DESC.")
        ordering.append(f"{column} {direction.upper()}")
    if names:
        # Validate real columns without fetching table rows or requiring catalog access.
        with db.conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {qualified} WHERE 1 = 0")
            available = {column[0].casefold() for column in cursor.description}
        if any(name.casefold() not in available for name in names):
            raise ValueError("Unknown selected, filtered or ordering column.")
    sql = f"SELECT {('TOP ' + str(limit) + ' ') if limit is not None else ''}{projection} FROM {qualified}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if ordering:
        sql += " ORDER BY " + ", ".join(ordering)
    return sql, parameters


def export_file(db, table, path, *, schema="SQLUser", overwrite=False, chunk_size=10000,
                columns=None, filters=None, order_by=None, limit=None, **kwargs):
    """Export a whole table or structured subset through the shared query writer."""
    sql, parameters = table_query(db, table, schema=schema, columns=columns,
                                  filters=filters, order_by=order_by, limit=limit)
    return export_query(db, sql, path, parameters=parameters, overwrite=overwrite,
                        chunk_size=chunk_size, **kwargs)


def export_query(db, sql, path, *, parameters=None, overwrite=False, chunk_size=10000, **kwargs):
    """Export CSV/JSON/JSONL in bounded chunks; XLSX uses a pandas DataFrame.

    Publish the completed file only after success. Existing output is preserved
    on failure, including with overwrite=True. Returns a path and row count.
    """
    if chunk_size is not None:
        _positive(chunk_size, "chunk_size")
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".json", ".jsonl", ".xlsx"}:
        raise ValueError("Choose a CSV, JSON, JSONL or XLSX output file.")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty query.")
    if path.exists() and not overwrite:
        raise FileExistsError("Output exists; use overwrite=True to replace it.")
    if suffix == ".xlsx":
        try:
            import openpyxl  # noqa: F401
        except ImportError as exc:
            raise ImportError('Install Excel support with: pip install "iristool[excel]"') from exc
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=suffix)
    os.close(descriptor)
    temporary = Path(temporary)
    count = 0
    try:
        if suffix == ".xlsx" or kwargs or chunk_size is None:
            # Arbitrary pandas options (e.g. JSON orient) can require the whole frame.
            frame = db.fetch(sql, parameters=parameters)
            if suffix == ".xlsx":
                frame.to_excel(temporary, **{"index": False, "engine": "openpyxl", **kwargs})
            elif suffix == ".csv":
                frame.to_csv(temporary, **{"index": False, **kwargs})
            else:
                frame.to_json(temporary, **{"orient": "records", "date_format": "iso",
                                            "lines": suffix == ".jsonl", **kwargs})
            count = None if suffix == ".xlsx" else len(frame)
        else:
            with db.conn.cursor() as cursor, temporary.open("w", encoding="utf-8", newline="") as output:
                if parameters:
                    cursor.execute(sql, parameters)
                else:
                    cursor.execute(sql)
                if cursor.description is None:
                    raise ValueError("Export query must return a tabular result.")
                columns = [col[0] for col in cursor.description]
                if len(set(columns)) != len(columns):
                    raise ValueError("Query columns must have unique names; use SQL aliases.")
                if suffix == ".json":
                    output.write("[")
                first = True
                while True:
                    rows = cursor.fetchmany(chunk_size)
                    if not rows:
                        if first and suffix == ".csv":
                            pd.DataFrame(columns=columns).to_csv(output, index=False)
                        break
                    # Object dtype prevents large nullable integers becoming floats.
                    frame = pd.DataFrame(rows, columns=columns, dtype=object)
                    if suffix == ".csv":
                        frame.to_csv(output, index=False, header=first)
                    elif suffix == ".jsonl":
                        frame.to_json(output, orient="records", lines=True, date_format="iso")
                    else:
                        if not first:
                            output.write(",")
                        output.write(frame.to_json(orient="records", date_format="iso")[1:-1])
                    first = False
                    count += len(rows)
                if suffix == ".json":
                    output.write("]")
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # Atomic no-clobber publication on the same filesystem.
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(path), "rows": count}
