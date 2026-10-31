import iris.dbapi
import re
from itertools import islice
import pandas as pd
import logging
from pandas.api import types as ptypes
import datetime as dt
from pathlib import Path

logger = logging.getLogger(__name__)

class IRIStool:
    def __init__(self, host = "127.0.0.1", port = 1972, namespace = 'USER', username = '_SYSTEM', password = 'SYS'):
        """
        Initialize an IRIS connection object with the given parameters.

        Parameters:
            host (str): The hostname or IP address of the IRIS server. Defaults to "127.0.0.1".
            port (int): The port number of the IRIS superserver. Defaults to 1972.
            namespace (str): The namespace of the IRIS database. Defaults to 'USER'.
            username (str): The username to use when connecting to IRIS. Defaults to '_SYSTEM'.
            password (str): The password to use when connecting to IRIS. Defaults to 'SYS'.
        """
        try:
            if isinstance(port, str):
                port = int(port)
        except ValueError:
            raise ValueError("Port must be an integer or convertable to an integer.")

        self.host = host  # localhost = 127.0.0.1
        self.port = port # superserver port
        self.namespace = namespace
        self.username = username
        self.password = password

        # Open a connection to the server
        args = {
            'hostname':host,
            'port': port,
            'namespace':namespace,
            'username': username,
            'password': password
        }
        self.conn = iris.dbapi.connect(**args, autoCommit=False)

    # ---------- Dunders ----------
    def __repr__(self) -> str:
        """
        Return a string representation of the IRIS connection object.

        Returns:
            str: A string representation of the IRIS connection object.

        Example:
            print(repr(conn))
        Output:
            IRIStool(host='127.0.0.1', port=9091, namespace='USER', user='_SYSTEM')
        """
        return ( f"IRIStool(host='{self.host}', port={self.port}, namespace='{self.namespace}', " f"user='{self.username}')" )

    def __str__(self) -> str:
        """
        Return a string representation of the IRIS connection object.

        Returns:
            str: A string representation of the IRIS connection object.

        Example:
            print(conn)
        Output:
            IRIS connection [_SYSTEM@127.0.0.1:1972/USER]
        """
        return f"IRIS connection [{self.username}@{self.host}:{self.port}/{self.namespace}]"

    def __enter__(self):
        """
        Enter the runtime context related to this object.

        Returns:
            IRIStool: self

        Example:
            with IRIStool() as conn:
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Exit the runtime context related to this object.

        It will automatically close the connection to the IRIS server.

        Example:
            at exit of the runtime context related to this object: with IRIStool() as conn:
        """
        self.close()

    def close(self):
        """
        Close the connection to the IRIS server.

        If the connection is not already closed, it will be closed and set to None.
        """
        if hasattr(self, "conn") and self.conn:
            self.conn.close()
            self.conn = None

    # ---------- Validation ----------
    @staticmethod
    def _identifier(name: str) -> str:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError(f"Invalid SQL identifier: {name!r}. Use letters, digits and underscores, starting with a letter.")
        return f'"{name}"'

    @staticmethod
    def _column_names(columns) -> list[str]:
        names = [str(col).strip().replace(" ", "_").replace(".", "_") for col in columns]
        if not names:
            raise ValueError("At least one column is required.")
        for name in names:
            IRIStool._identifier(name)
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Column names collide after normalization.")
        return names

    def validate_table_name(self, table_name: str, table_schema: str = None) -> str:
        """Validate separate table/schema identifiers and return the qualified name."""
        self._identifier(table_name)
        if table_schema is not None:
            self._identifier(table_schema)
            return f"{table_schema}.{table_name}"
        return table_name

    def get_name_and_schema(self, full_name: str) -> tuple[str, str]:
        """Split a qualified table name, defaulting to SQLUser."""
        if not isinstance(full_name, str):
            raise ValueError("The table name must be a string.")
        parts = full_name.split(".")
        if len(parts) == 1:
            schema, table = "SQLUser", parts[0]
        elif len(parts) == 2:
            schema, table = parts
        else:
            raise ValueError("Use schema.table or table.")
        self.validate_table_name(table, schema)
        return table, schema

    # ---------- Query ----------
    def fetch(self, sql: str, parameters: list | None = None) -> pd.DataFrame | None:
        """
        Execute a SQL query and return the result as a pandas DataFrame.

        Args:
            sql (str): The SQL query to execute.
            parameters (list, optional): The parameters to pass to the query. Defaults to an empty list.

        Returns:
            pd.DataFrame | None: A pandas DataFrame containing the query result, or None if the query returns no rows.

        Raises:
            Exception: If there is an error executing the query.

        Example:
            df = conn.fetch("SELECT * FROM my_table WHERE id = ? AND name = ?", parameters=[1, "test"])
        """
        try:
            with self.conn.cursor() as cursor:
                # execute the query
                if parameters:
                    cursor.execute(sql, parameters)
                else:
                    cursor.execute(sql)
                # Fetch all rows at once
                rows = cursor.fetchall()
                # Extract column names from cursor description
                columns = [col[0] for col in (cursor.description or [])]
                # Create DataFrame in one shot
                df = pd.DataFrame(rows, columns=columns)
                return df
        except Exception as e:
            print(f"Error executing query: {e}")
            raise   # re-raise to let caller handle it

    def import_file(self, path, table_name: str, table_schema: str = "SQLUser", *,
                    replace=False, column_types=None, batch_size=1000,
                    chunk_size=None, separator=None, sheet_name=0) -> int:
        """Import CSV/TSV, JSON/JSONL or XLSX; return the inserted row count.

        Set chunk_size with complete column_types for bounded-memory CSV/JSONL
        imports. Without chunk_size the full input is used for type inference.
        Inserts share one transaction; table creation/replacement commits first.
        """
        from .transfer import import_file
        return import_file(self, path, table_name, schema=table_schema,
                           replace=replace, column_types=column_types,
                           batch_size=batch_size, chunk_size=chunk_size,
                           separator=separator, sheet_name=sheet_name)

    def export_table(self, table_name: str, path, table_schema: str = "SQLUser",
                     *, overwrite: bool = False, chunk_size: int | None = 10000,
                     columns=None, filters=None, order_by=None, limit=None, **kwargs) -> Path:
        """Export CSV, JSON/JSONL or XLSX, atomically publishing a completed file.

        CSV/JSON/JSONL stream in bounded chunks by default. XLSX, custom pandas
        writer kwargs, or chunk_size=None use a whole-table DataFrame. CSV/XLSX
        omit the pandas index; JSON defaults to records with ISO dates. XLSX
        requires iristool[excel]. Returns Path; parent directories must exist.
        Optional columns, ANDed filters ({column, op, value}), order_by
        ({column, direction}) and positive limit select a subset inside IRIS.
        NULL filters omit value; IN uses a non-empty list. No SQL fragments.
        """
        from .transfer import export_file
        export_file(self, table_name, path, schema=table_schema,
                    overwrite=overwrite, chunk_size=chunk_size, columns=columns,
                    filters=filters, order_by=order_by, limit=limit, **kwargs)
        return Path(path)

    def export_query(self, sql: str, path, parameters=None, *, overwrite=False,
                     chunk_size: int | None = 10000, **kwargs) -> Path:
        """Export a query result with bound parameters and atomic file publication.

        CSV/JSON/JSONL stream via fetchmany. XLSX, custom pandas writer options,
        or chunk_size=None materialize the result. SQL executes with the account's
        permissions; this Python API does not enforce read-only SQL. Use unique
        column aliases for joins. Does not commit or close the connection.
        """
        from .transfer import export_query
        export_query(self, sql, path, parameters=parameters, overwrite=overwrite,
                     chunk_size=chunk_size, **kwargs)
        return Path(path)

    def insert_row(self, table_name: str, values: dict, table_schema: str = "SQLUser") -> None:
        """
        Insert a row into a table.

        Args:
            table_name (str): The table to insert into (name only, without schema).
            values (dict): {column: value, ...}
            table_schema (str): Schema (default SQLUser)

        Example:
            conn.insert_row("ExportResponse", {"col1": "value1", "col2": 123}, "EnsLib_Background_Workflow")
        """
        # Validate table
        full_name = self.validate_table_name(table_name, table_schema)
        columns = ', '.join(self._identifier(col) for col in self._column_names(values))
        placeholders = ', '.join(['?'] * len(values))
        sql = f"INSERT INTO {full_name} ({columns}) VALUES ({placeholders})"
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, tuple(values.values()))
                self.conn.commit()
                # print(f"Inserted row into {full_name}: {values}")
        except Exception as e:
            self.conn.rollback()
            print(f"Failed to insert into {full_name}: {e}")
            raise

    def insert_many(
        self,
        table_name: str,
        rows: list[dict],
        table_schema: str = "SQLUser"
    ) -> int:
        """
        Insert multiple rows into a table at once.

        Args:
            table_name (str): The table to insert into.
            rows (list[dict]): List of dicts, each representing a row.
            table_schema (str, optional): Schema name. Defaults to "SQLUser".

        Returns:
            int: Number of rows inserted.

        Example:
            conn.insert_many("my_table", [{"col1": "value1", "col2": 123}, {"col1": "value2", "col2": 456}])
        """
        if not rows:
            return 0
        full_table = self.validate_table_name(table_name, table_schema)
        try:
            with self.conn.cursor() as cursor:
                columns = rows[0].keys()
                col_str = ",".join(self._identifier(col) for col in self._column_names(columns))
                placeholders = ", ".join(["?"] * len(columns))
                sql = f"INSERT INTO {full_table} ({col_str}) VALUES ({placeholders})"
                values = [tuple(row[col] for col in columns) for row in rows]
                self._execute_batch(cursor, sql, values)
                self.conn.commit()
                print(f"{cursor.rowcount} row(s) added into {full_table}.")
                return cursor.rowcount
        except Exception as e:
            self.conn.rollback()
            print(f"Failed to insert into {full_table}: {e}")
            raise

    # ---------- Tables Management ----------
    def create_table(self,
                    table_name: str,
                    columns: dict[str, str],
                    constraints: list[str] | None = None,
                    table_schema: str = "SQLUser",
                    check_exists: bool = False) -> None:
        """
        Create a table in the database.

        Args:
            table_name (str): The name of the table to create.
            columns (dict[str, str]): A dictionary of column names to their respective data types.
            constraints (list[str] | None, optional): A list of constraints to apply to the table. Defaults to None.
            table_schema (str, optional): The schema of the table to create. Defaults to None.
            check_exists (bool, optional): If True, raise an error if the table already exists.

        Raises:
            ValueError: If the table already exists and check_exists is True.
            Exception: If there is an error creating the table.

        Example:
            conn.create_table("my_table", {"id": "INTEGER", "name": "VARCHAR(255)"}, ["PRIMARY KEY (id)"])
        """
        full_table_name = self.validate_table_name(table_name=table_name, table_schema=table_schema)
        if check_exists and self.table_exists(table_name=table_name, table_schema=table_schema):
            raise ValueError(f"Table {table_name} already exists.")
        col_defs = [f"{self._identifier(col)} {ctype}" for col, ctype in columns.items()]
        if constraints:
            col_defs.extend(constraints)
        sql = f"CREATE TABLE {full_table_name} ( {', '.join(col_defs)} )"
        try:
            with self.conn.cursor() as cursor:
                # execute the query
                cursor.execute(sql)
                self.conn.commit()
                print(f"Table {full_table_name} created successfully.")
        except Exception as e:
            self.conn.rollback()
            print(f"Error creating table {full_table_name}: {e}")
            raise

    def drop_table(self, table_name: str, table_schema: str = "SQLUser", if_exists: bool = True, drop_related_views: bool = False, view_or_table: str = "table") -> None:
        """
        Drop a SQL table with the given name.

        Args:
            table_name (str): The name of the table to drop.
            table_schema (str): The schema of the table to drop (default: "SQLUser").
            if_exists (bool): If True, use 'IF EXISTS' SQL statement to avoid errors when the table doesn't exist (default: True).
                            If False, it will raise an error if the table doesn't exist.
            drop_related_views (bool): If True, drop related views if they exist (default: False).
            view_or_table (str): The type of object to drop, either "table" or "view" (default: "table").

        Example:
            conn.drop_table("my_table")
        """
        full_name = self.validate_table_name(table_name, table_schema)
        if view_or_table.lower() not in {"table", "view"}:
            raise ValueError("view_or_table must be table or view.")
        if drop_related_views:
            # check if related views exist
            for related_view in self.views_using_table(table_name=table_name, table_schema=table_schema):
                self.drop_table(
                    table_name=related_view['VIEW_NAME'],
                    table_schema=related_view['VIEW_SCHEMA'],
                    if_exists=False,
                    view_or_table="view"
                )
        sql = f"DROP {view_or_table} {'IF EXISTS ' if if_exists else ''}{full_name}"
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql)
                self.conn.commit()
                print(f"{view_or_table} {full_name} dropped successfully.")
        except Exception as e:
            self.conn.rollback()
            print(f"Error dropping {view_or_table} {full_name}: {e}")
            raise

    def update(
        self,
        table_name: str,
        new_values: dict,
        filters: dict,
        table_schema: str = "SQLUser"
    ) -> int:
        """
        Update rows in a table given new values and filter conditions.

        Args:
            table_name (str): The table to update.
            new_values (dict): Column=value pairs to set.
            filters (dict): Column=value pairs for the WHERE clause.
            table_schema (str, optional): Schema of the table. Defaults to 'SQLUser'.

        Returns:
            int: Number of rows affected.

        Example:
            conn.update("my_table", {"col1": "new_value1", "col2": "new_value2"}, {"id": 1})
        """
        full_table = self.validate_table_name(table_name, table_schema)
        try:
            with self.conn.cursor() as cursor:
                # SET clause
                set_clause = ", ".join([f"{self._identifier(col)} = ?" for col in self._column_names(new_values)])
                set_values = list(new_values.values())
                # WHERE clause
                where_clause = " AND ".join([f"{self._identifier(col)} = ?" for col in self._column_names(filters)])
                where_values = list(filters.values())
                sql = f"UPDATE {full_table} SET {set_clause} WHERE {where_clause}"
                cursor.execute(sql, set_values + where_values)
                self.conn.commit()
                rowcount = cursor.rowcount
                print(f"Updated {rowcount} row(s) in {full_table}.")
                return rowcount
        except Exception as e:
            self.conn.rollback()
            print(f"Failed to update {full_table}: {e}")
            raise

    def update_many(
        self,
        table_name: str,
        updates: list[tuple[dict, dict]],
        table_schema: str = "SQLUser"
    ) -> int:
        """
        Update multiple rows in a table.

        Args:
            table_name (str): The table to update.
            updates (list[tuple[dict, dict]]): List of (new_values, filters) dict pairs.
            table_schema (str, optional): Schema. Defaults to "SQLUser".

        Returns:
            int: Total rows updated.

        Example:
            conn.update_many("my_table", [
                ({'col1': 'new_value1', 'col2': 'new_value2'}, {'id': 1}),
                ({'col1': 'new_value3', 'col2': 'new_value4'}, {'id': 2})
            ])
        """
        if not updates:
            return 0
        full_table = self.validate_table_name(table_name, table_schema)
        total = 0
        try:
            with self.conn.cursor() as cursor:
                for new_values, filters in updates:
                    set_clause = ", ".join([f"{self._identifier(col)} = ?" for col in self._column_names(new_values)])
                    set_values = list(new_values.values())
                    where_clause = " AND ".join([f"{self._identifier(col)} = ?" for col in self._column_names(filters)])
                    where_values = list(filters.values())
                    sql = f"UPDATE {full_table} SET {set_clause} WHERE {where_clause}"
                    cursor.execute(sql, set_values + where_values)
                    total += cursor.rowcount
                self.conn.commit()
                print(f"Updated {total} row(s) in {full_table}.")
                return total
        except Exception as e:
            self.conn.rollback()
            print(f"Failed to update {full_table}: {e}")
            raise

    def table_exists(self, table_name: str, table_schema: str = "SQLUser") -> bool:
        """
        Check if a table exists in the database.

        Args:
            table_name (str): The name of the table to check.
            table_schema (str, optional): The schema of the table to check. Defaults to "SQLUser".

        Returns:
            bool: True if the table exists, False otherwise.

        Example:
            conn.table_exists("my_table")
        """
        self.validate_table_name(table_name, table_schema)

        parameters = [table_name, table_schema]
        query = f"""
            SELECT COUNT(*) as num_rows
            FROM INFORMATION_SCHEMA.TABLES
            WHERE table_name = ?
            AND table_schema = ?
        """

        exists_df = self.fetch(query, parameters)
        exists = int(exists_df['num_rows'][0]) > 0

        return exists

    def describe_table(self, table_name: str, table_schema: str = "SQLUser") -> dict:
        """
        Retrieve metadata about a table: columns and indices.

        Args:
            table_name (str): The name of the table to describe.

        Returns:
            dict: A dictionary containing metadata about the table, including columns and indices.

        Example:
            conn.describe_table("my_table")
        """
        self.validate_table_name(table_name, table_schema)
        info = {}
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT TABLE_SCHEMA, TABLE_NAME,
                    column_name, data_type, character_maximum_length,
                    is_nullable, AUTO_INCREMENT, UNIQUE_COLUMN, PRIMARY_KEY, odbctype
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE table_name = ?
                    AND table_schema = ?
                """,
                [table_name, table_schema])
                columns = cursor.fetchall()
                info["columns"] = [
                    dict(zip([col[0] for col in cursor.description], row)) for row in columns
                ]

                # Indexes
                cursor.execute(f"""
                    SELECT index_name, column_name, PRIMARY_KEY, NON_UNIQUE
                    FROM INFORMATION_SCHEMA.INDEXES
                    WHERE table_name = ?
                    AND table_schema = ?
                """,
                [table_name, table_schema])
                indexes = cursor.fetchall()
                info["indexes"] = [
                    dict(zip([col[0] for col in cursor.description], row)) for row in indexes
                ]
            return info
        except Exception as e:
            print(f"Error describing table: {e}")
            raise

    def get_reference_from_this_table(self, table_name: str, table_schema: str = "SQLUser"):
        """
        Get all the foreign key references from this table.

        Args:
            table_name (str): The name of the table to get references from.
            table_schema (str, optional): The schema of the table to get references from. Defaults to "SQLUser".

        Returns:
            DataFrame: A DataFrame containing the reference information.
        """
        sql = """
        SELECT
            c.CONSTRAINT_NAME as constraint_name,
            c.UNIQUE_CONSTRAINT_TABLE as referenced_table,
            c.UNIQUE_CONSTRAINT_SCHEMA as referenced_schema,
            k.TABLE_SCHEMA as table_schema,
            k.TABLE_NAME as table_name,
            k.COLUMN_NAME as column_name,
            k.REFERENCED_COLUMN_NAME as referenced_column_name
        FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS c
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS k
            ON c.CONSTRAINT_NAME = k.CONSTRAINT_NAME
        WHERE k.TABLE_SCHEMA = ? AND k.TABLE_NAME = ?
        """
        return self.fetch(sql, [table_schema, table_name])

    def get_reference_to_this_table(self, table_name: str, table_schema: str = "SQLUser"):
        """
        Get all the foreign key references to this table.

        Args:
            table_name (str): The name of the table to get references to.
            table_schema (str, optional): The schema of the table to get references to. Defaults to "SQLUser".

        Returns:
            DataFrame: A DataFrame containing the reference information.
        """
        sql = """
        SELECT
            c.CONSTRAINT_NAME as constraint_name,
            c.UNIQUE_CONSTRAINT_TABLE as referenced_table,
            c.UNIQUE_CONSTRAINT_SCHEMA as referenced_schema,
            k.TABLE_SCHEMA as table_schema,
            k.TABLE_NAME as table_name,
            k.COLUMN_NAME as column_name,
            k.REFERENCED_COLUMN_NAME as referenced_column_name
        FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS c
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS k
            ON c.CONSTRAINT_NAME = k.CONSTRAINT_NAME
        WHERE c.UNIQUE_CONSTRAINT_SCHEMA = ? AND c.UNIQUE_CONSTRAINT_TABLE = ?
        """
        return self.fetch(sql, [table_schema, table_name])

    def get_row_id(self, table_name: str, column_name: str, value: str, table_schema: str = "SQLUser") -> int:
        """
        Retrieve the row ID from a table given a column name and value.

        Args:
            table_name (str): The name of the table to query.
            column_name (str): The name of the column to search for.
            value (str): The value to search for in the column.

        Returns:
            int: The row ID associated with the given column name and value.

        Raises:
            Exception: If there is an error executing the query.

        Example:
            conn.get_row_id("my_table", "my_column", "my_value")
        """
        full_name = self.validate_table_name(table_name, table_schema)
        sql = f"SELECT ID FROM {full_name} WHERE {self._identifier(column_name)} = ?"
        try:
            id_df = self.fetch(sql, parameters=[value])
            return int(id_df["ID"][0])
        except Exception as e:
            print(f"Error getting row ID: {e}")
            raise

    def add_columns(self, table_name: str, new_columns: dict[str, str], table_schema: str = "SQLUser") -> None:
        """
        Add new columns to a table.

        Args:
            table_name (str): The name of the table to add columns to.
            new_columns (dict[str, str]): A dictionary of column name to data type pairs.

        Raises:
            Exception: If there is an error executing the query.

        Example:
            conn.add_columns("my_table", {"new_column": "VARCHAR(255)"})
        """
        full_name = self.validate_table_name(table_name, table_schema)
        try:
            with self.conn.cursor() as cursor:
                for col, ctype in new_columns.items():
                    sql = f"ALTER TABLE {full_name} ADD {self._identifier(col)} {ctype}"
                    cursor.execute(sql)
                    print(f"Added column {col} {ctype} to {table_name}")
                    self.conn.commit()
        except Exception as e:
            self.conn.rollback();
            print(f"Error adding columns: {e}");
            raise

    # ---------- DataFrame → Table ----------
    def df_to_table(self,
                df: pd.DataFrame,
                table_name: str,
                table_schema: str = "SQLUser",
                column_types: dict[str, str] | None = None,
                primary_key: str | None = None,
                constraints: list[str] | None = None,
                exist_ok: bool = False,
                drop_if_exists: bool = False,
                drop_related_views: bool = False,
                indices: list[dict] | None = None,
                batch_size: int = 1000
        ) -> None:
        """
        Insert a pandas DataFrame into a table in the database.

        Args:
            df (pd.DataFrame): The DataFrame to insert into the table.
            table_name (str): The name of the table to create.
            column_types (dict[str, str], optional): A dictionary of column name to data type pairs. Defaults to None, which infers types from the DataFrame.
            primary_key (str, optional): The name of the primary key column. Defaults to None.
            constraints (list[str], optional): A list of constraints to apply to the table. Defaults to None.
            exist_ok (bool, optional): If True, check if the table already exists and skip creation or drop it if it does. Defaults to False.
            drop_if_exists (bool, optional): If True and if exist_ok is True, drop the table if it already exists. Defaults to False.
            drop_related_views (bool, optional): If True, drop related views if they exist. Defaults to False.
            indices (list[dict], optional): A list of index definitions. Defaults to None.
            batch_size (int): Rows submitted per batch. Defaults to 1000.

        Raises:
            Exception: If there is an error executing the query.

        Example:
            conn.df_to_table(
                df=df,
                table_name=table_name,
                table_schema=table_schema,
                primary_key="ID",
                constraints=[
                    "FOREIGN KEY(patient_id) REFERENCES Test.Patient(patient_row_id)"
                ],
                exist_ok=True,
                drop_if_exists=True,
                drop_related_views=True,
                indices=[
                    {"column": "Age", "type": "index"},           # normal index
                    {"column": "Name", "type": "unique"},         # unique index
                    {"column": "Embedding", "type": "hnsw", "params": {"distance": "Cosine", "M": 16, "ef_construct": 200}}
                ]
            )
        """
        full_name = self.validate_table_name(table_name, table_schema)
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer.")
        columns = self._column_names(df.columns)
        if column_types is None:
            column_types = self.infer_iris_types(df)
        else:
            normalized_types = self._column_names(column_types)
            column_types = dict(zip(normalized_types, column_types.values()))
            if set(column_types) != set(columns):
                raise ValueError("column_types must match the DataFrame columns.")
        if primary_key:
            primary_key = self._column_names([primary_key])[0]
            if primary_key not in columns:
                raise ValueError("primary_key must name a DataFrame column.")
            primary_key = self._identifier(primary_key)
        if exist_ok and self.table_exists(table_name, table_schema):
            if drop_if_exists:
                self.drop_table(table_name, table_schema, drop_related_views=drop_related_views)
            else:
                logger.info("Table %s already exists; skipping import.", full_name)
                return

        # Collect constraints
        all_constraints = []
        if primary_key:
            all_constraints.append(f"PRIMARY KEY ({primary_key})")
        if constraints:
            all_constraints.extend(constraints)

        # create table
        self.create_table(
            table_name=table_name,
            table_schema=table_schema,
            columns=column_types,
            constraints=all_constraints
        )

        # add indices
        if indices:
            for idx in indices:
                col = idx["column"]
                col = col.strip()
                col = col.replace(" ","_")
                col = col.replace(".","_")
                idx_type = idx.get("type", "index")
                idx_name = idx.get("name", f"{table_name}_{col}_{idx_type}")

                if idx_type == "hnsw":
                    params = idx.get("params", {})
                    self.create_hnsw_index(
                        table_name=table_name,
                        column_name=col,
                        index_name=idx_name,
                        distance=params.get("distance", "Cosine"),
                        M=params.get("M"),
                        ef_construct=params.get("ef_construct"),
                        table_schema=table_schema
                    )
                else:
                    self.create_index(
                        index_name=idx_name,
                        table_name=table_name,
                        column_name=col,
                        index_type=idx.get("type", "index"),
                        table_schema=table_schema
                    )

        try:
            with self.conn.cursor() as cursor:
                placeholders = ", ".join(["?"] * len(columns))
                sql = f"INSERT INTO {full_name} ({', '.join(self._identifier(col) for col in columns)}) VALUES ({placeholders})"
                # Keep per-column Python types: df.values can round mixed int/float rows.
                rows = (tuple(self._sql_value(value) for value in row)
                        for row in df.itertuples(index=False, name=None))
                while batch := list(islice(rows, batch_size)):
                    self._execute_batch(cursor, sql, batch)
                self.conn.commit()
                logger.info("Inserted %s rows into %s", len(df), full_name)
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Converting DataFrame to table failed: {e}") from e

    @staticmethod
    def _execute_batch(cursor, sql, rows):
        # IRIS can return per-row error strings without raising an exception.
        results = cursor.executemany(sql, rows)
        if results is not None and any(isinstance(result, str) for result in results):
            raise RuntimeError(f"Batch insertion failed: {results!r}")
        if cursor.rowcount not in (-1, len(rows)):
            raise RuntimeError(f"Expected {len(rows)} inserted rows, got {cursor.rowcount}: {results!r}")

    @staticmethod
    def _sql_value(value):
        """Convert pandas/numpy scalar values to DB API values."""
        if not ptypes.is_scalar(value):
            raise ValueError("Non-scalar values require conversion before SQL insertion.")
        if pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            if value.tzinfo is not None:
                raise ValueError("Convert timezone-aware datetimes to naive datetimes before insertion.")
            return value.to_pydatetime()
        if hasattr(value, "item"):
            return value.item()
        return value

    @staticmethod
    def infer_iris_types(df, column_types=None):
        """Infer types from non-null values without modifying supplied overrides."""
        names = IRIStool._column_names(df.columns)
        inferred = dict(column_types or {})
        for original, name in zip(df.columns, names):
            if name in inferred:
                continue
            series = df[original]
            values = series.dropna()
            sql_type = "VARCHAR(255)"
            if ptypes.is_bool_dtype(series):
                sql_type = "BIT"
            elif ptypes.is_integer_dtype(series):
                sql_type = "INT"
                if not values.empty:
                    minimum, maximum = int(values.min()), int(values.max())
                    if minimum < -(2**63) or maximum > 2**63 - 1:
                        sql_type = "DECIMAL(20,0)"
                    elif minimum < -(2**31) or maximum > 2**31 - 1:
                        sql_type = "BIGINT"
            elif ptypes.is_float_dtype(series):
                sql_type = "DOUBLE"
            elif ptypes.is_datetime64_any_dtype(series):
                if isinstance(series.dtype, pd.DatetimeTZDtype):
                    raise ValueError("Convert timezone-aware datetimes before SQL type inference.")
                sql_type = "DATETIME"
                if not values.empty and (values.dt.time == dt.time()).all():
                    sql_type = "DATE"
                elif not values.empty and (values.dt.date == dt.date(1970, 1, 1)).all():
                    sql_type = "TIME"
            elif not values.empty:
                if all(isinstance(v, dt.datetime) for v in values):
                    sql_type = "DATETIME"
                elif all(isinstance(v, dt.date) for v in values):
                    sql_type = "DATE"
                elif all(isinstance(v, dt.time) for v in values):
                    sql_type = "TIME"
                elif values.astype(str).map(len).max() > 255:
                    sql_type = "CLOB"
            inferred[name] = sql_type
        return inferred

    # ---------- Indexes ----------
    def index_exists(self, table_name: str, index_name: str, table_schema: str = "SQLUser") -> bool:
        """
        Check if an index exists on a given table.

        Args:
            table_name (str): The name of the table to check.
            index_name (str): The name of the index to check.
            table_schema (str, optional): The schema of the table. Default is "SQLUser".

        Returns:
            bool: True if the index exists, False otherwise.

        Example:
            conn.index_exists("my_table", "my_index")
        """
        self.validate_table_name(table_name, table_schema)
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.INDEXES
            WHERE table_name = ?
            AND table_schema = ?
            AND index_name = ?
        """,
        [table_name, table_schema, index_name])
        exists = cursor.fetchone()[0] > 0
        cursor.close()
        return exists

    def create_index(self, index_name: str, table_name: str, column_name: str, index_type: str = "index", table_schema: str = "SQLUser") -> None:
        """
        Create an index on a given table and column.

        Args:
            index_name (str): The name of the index.
            table_name (str): The table to add the index to.
            column_name (str): The column to index.
            index_type (str): Type of index (e.g., 'INDEX', 'COLUMNAR', 'BITSLICE', 'BITMAP', ''). Default: 'index'.

        Example:
            conn.create_index("my_index", "my_table", "my_column")
        """
        full_name = self.validate_table_name(table_name, table_schema)
        if self.index_exists(table_name, index_name, table_schema):
            raise ValueError(f"Index {index_name} already exists on {full_name}.")

        index_type = index_type.lower()
        if index_type not in {"", "index", "unique", "bitmap", "bitslice", "columnar"}:
            raise ValueError("Unsupported index type.")
        index_name = self._identifier(index_name)
        column_name = self._identifier(column_name)
        if index_type != "" and index_type != "index":
            sql = f"CREATE {index_type} INDEX {index_name} ON {full_name}({column_name})"
        else:
            sql = f"CREATE INDEX {index_name} ON {full_name}({column_name})"

        cursor = self.conn.cursor()
        try:
            cursor.execute(sql)
            self.conn.commit()
            print(f"Index {index_name} created successfully on {full_name}({column_name}).")
        except Exception as e:
            self.conn.rollback()
            print(f"Error creating index {index_name} on {full_name}: {e}")
            raise
        finally:
            cursor.close()

    def create_hnsw_index(self,
                          table_name: str,
                          column_name: str,
                          index_name: str,
                          distance: str = "Cosine",
                          M: int = None,
                          ef_construct: int = None,
                          table_schema: str = "SQLUser") -> None:
        """
        InterSystems SQL allows you to define a Hierarchical Navigable Small World (HNSW) index,
        which uses the HNSW algorithm to create a vector index.

        You can define an HNSW index using a CREATE INDEX statement.  To define an HNSW index,
        the following requirements must be met:

        * The HNSW index is defined on a VECTOR-typed field with a fixed length that is of
            type FLOAT, DOUBLE, or DECIMAL.
        * The table the index is defined on must have IDs that are bitmap-supported.
        * The table the index is defined on must use default storage.

        There are three parameters you can specify when defining an HNSW index:

        * **Distance (required):** The distance function used by the index, surrounded by quotes ('').
            Possible values are Cosine and DotProduct. This parameter is case-insensitive.
        * **M (optional):** The number of bi-directional links created for every new element during
            construction. This value should be a positive integer larger than 1; the value will fall
            between 2 and 100. Higher M values work better on datasets with high dimensionality or
            recall, while lower M values work better with low dimensionality or recall.
            The default value is 64.
        * **efConstruct (optional):** The size of the dynamic list for the nearest neighbors. This
            value should be a positive integer larger than M. Larger efConstruct values generally
            lead to better index quality but longer construction time.  There is a maximum value
            past which efConstruct does not improve the quality of the index.
            The default value is 64.

        Args:
            table_name (str): The name of the table to add the index to.
            column_name (str): The column to index.
            index_name (str): The name of the index.
            distance (str): The distance function used by the index. Default: "Cosine".
            M (int): The number of bi-directional links created for every new element during construction. Default: None.
            ef_construct (int): The size of the dynamic list for the nearest neighbors. Default: None.

        Example:
            conn.create_hnsw_index("my_table", "my_column", "my_index", distance="Cosine", M=64, ef_construct=64)
        """
        full_name = self.validate_table_name(table_name, table_schema)
        index_name = self._identifier(index_name)
        column_name = self._identifier(column_name)
        if distance.lower() not in {"cosine", "dotproduct"}:
            raise ValueError("distance must be Cosine or DotProduct.")
        if M is not None and (isinstance(M, bool) or not isinstance(M, int) or not 2 <= M <= 100):
            raise ValueError("M must be an integer between 2 and 100.")
        if ef_construct is not None and (isinstance(ef_construct, bool) or not isinstance(ef_construct, int) or ef_construct < 1):
            raise ValueError("ef_construct must be a positive integer.")
        params = [f"Distance='{distance}'"]
        if M:
            params.append(f"M={M}")
        if ef_construct:
            params.append(f"efConstruct={ef_construct}")
        param_str = ", ".join(params)

        sql = f"""
            CREATE INDEX {index_name}
            ON {full_name}({column_name})
            AS %SQL.Index.HNSW({param_str})
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql)
            self.conn.commit()
            print(f"Created HNSW index {index_name} on {full_name}({column_name})")
        except Exception as e:
            self.conn.rollback()
            logger.error("Failed to create HNSW index: %s", e)
            raise
        finally:
            cursor.close()

    def quick_create_index(self, table_name: str, column_name: str, table_schema: str = "SQLUser") -> None:
        """
        Convenience function to quickly create an index on a given table and column.
        If the index already exists, it will not be re-created and a message will be printed.
        The index name will be the column name followed by "_idx".
        The index type will be standard index.

        Args:
            table_name (str): The table to add the index to.
            column_name (str): The column to index.

        Returns:
            None

        Example:
            conn.quick_create_index("my_table", "my_column")
        """
        self.validate_table_name(table_name, table_schema)
        index_name = f"{column_name}_idx"
        if not self.index_exists(table_name=table_name, table_schema=table_schema, index_name=index_name):
            self.create_index(
                index_name=index_name,
                table_name=table_name,
                table_schema=table_schema,
                column_name=column_name
            )
        else:
            print(f"Index {index_name} already exists")

    # ---------- Views ----------
    def create_view(self, view_name: str, sql: str, view_schema: str = "SQLUser", exist_ok: bool = False, drop_if_exists: bool = False) -> None:
        """
        Create a view in the database.

        Args:
            view_name (str): The name of the view to create.
            sql (str): The SQL statement that defines the view.
            view_schema (str, optional): The schema of the view. Defaults to "SQLUser".
            exist_ok (bool, optional): If True, don't raise an error if the view already exists. Defaults to False.
            drop_if_exists (bool, optional): If True, drop the view if it already exists. Defaults to False.

        Returns:
            None

        Example:
            conn.create_view("my_view", "SELECT * FROM my_table", "EnsLib_Background_Workflow")
        """
        full_name = self.validate_table_name(view_name, view_schema)
        print(f"Creating view {full_name}...")
        if exist_ok == True:
            if self.table_exists(view_name, view_schema):
                print(f"View {full_name} already exists.")
                if drop_if_exists == True:
                    self.drop_table(view_name, view_schema, view_or_table="view")
                else:
                    print(f"View {full_name} already exists. Skipping creation.")
                    return
        elif exist_ok == False:
            if self.table_exists(view_name, view_schema):
                raise ValueError(f"View {full_name} already exists.")

        cursor = self.conn.cursor()
        try:
            cursor.execute(f"CREATE VIEW {full_name} AS {sql}")
            self.conn.commit()
            print(f"View {full_name} created.")
        except Exception as e:
            self.conn.rollback()
            print(f"Error creating view {full_name}: {e}")
            raise
        finally:
            cursor.close()

    def views_using_table(self, table_name: str, table_schema: str = "SQLUser") -> list[dict]:
        """
        Return a list of views that depend on a given table.

        Example:
            conn.views_using_table("my_table", "EnsLib_Background_Workflow")
        """
        sql = """
            SELECT TABLE_SCHEMA, TABLE_NAME, VIEW_SCHEMA, VIEW_NAME
            FROM INFORMATION_SCHEMA.VIEW_TABLE_USAGE
            WHERE TABLE_NAME = ? AND TABLE_SCHEMA = ?
        """
        df = self.fetch(sql, parameters=[table_name, table_schema])
        return df.to_dict(orient="records") if not df.empty else []

    # ---------- Namespace utilities ----------
    def show_namespace_tables(self, table_name: str | None = None, table_schema: str | None = None) -> pd.DataFrame:
        """
        Show all tables in a namespace.

        Args:
            table_name (str | None, optional): Filter by table name. Defaults to None.
            table_schema (str | None, optional): Filter by table schema. Defaults to None.

        Returns:
            pd.DataFrame: A DataFrame containing the results of the query.
        """
        sql = """
            SELECT TABLE_SCHEMA, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE='BASE TABLE'
        """
        parameters = []
        if table_name:
            sql += f" AND TABLE_NAME = ?"
            parameters.append(table_name)
        if table_schema:
            sql += f" AND TABLE_SCHEMA = ?"
            parameters.append(table_schema)
        sql += " ORDER BY TABLE_SCHEMA, TABLE_NAME"

        return self.fetch(sql,parameters)

    def show_namespace_schemas(self) -> pd.DataFrame:
        """
        Show all schemas in a namespace.

        Returns:
            pd.DataFrame: A DataFrame containing the results of the query.
        """
        sql = """
            SELECT TABLE_SCHEMA
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE='BASE TABLE'
            GROUP BY TABLE_SCHEMA
            ORDER BY TABLE_SCHEMA
        """
        return self.fetch(sql)
