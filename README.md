**iristool**

Load pandas DataFrames into InterSystems IRIS and query them with Python.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat)![InterSystems IRIS](https://img.shields.io/badge/InterSystems-IRIS-00a99d?style=flat)![MIT License](https://img.shields.io/badge/license-MIT-2ea043?style=flat)

**iristool** is a small Python library for moving data between pandas and InterSystems IRIS. Create a SQL table from a DataFrame, run parameterized queries, and manage rows, tables, views, and indexes through one connection object.

Python runs in your own environment and connects to an existing IRIS server through the official `intersystems-irispython` DB API. Install the library on your laptop, in a notebook, or in a Python application; no Python packages need to be installed inside IRIS.

[Features](#features) · [Installation](#installation) · [Quick start](#quick-start) · [Examples](#examples) · [API](#api-reference) · [Testing](#development-and-testing) · [Publishing](docs/publish.md)

---



## Features

- **DataFrame to SQL:** create a table, infer column types, and insert rows in batches.
- **SQL to DataFrame:** retrieve query results with optional bound parameters.
- **Data handling:** normalize column names and convert pandas missing values to SQL `NULL`.
- **Import control:** choose whether to fail, skip, or replace an existing table; supply explicit types, a primary key, constraints, and indexes.
- **SQL helpers:** insert and update rows, inspect metadata, and manage tables, columns, views, and indexes.
- **Small dependency list:** pandas and the official InterSystems Python SDK.

The library handles the IRIS part of a data workflow. Read a CSV with pandas, download data with another library, or construct a DataFrame yourself, then pass it to `df_to_table()`.

## Installation



### Requirements

- Python **3.10 or newer**, on a platform supported by the InterSystems SDK.
- A reachable **InterSystems IRIS 2022.1 or newer** server supporting the Python DB API.
- An IRIS account with SQL permissions for the operations you need.



### With pip

Once the first release is published on PyPI:

```bash
python -m pip install iristool
```

> **First release status:** this repository is prepared for PyPI publication. Until the first upload succeeds, install from the source checkout instead.

From the folder containing `pyproject.toml`:

```bash
python -m pip install .
```

For development, use `python -m pip install -e .`. Both installation methods install the runtime dependencies automatically. Import the class with:

```python
from iristool import IRIStool
```

## Quick start

Set your connection details. These example credentials are for the included local Docker development server:

```bash
export IRIS_HOST="localhost"
export IRIS_PORT="9091"
export IRIS_NAMESPACE="USER"
export IRIS_USER="_SYSTEM"
export IRIS_PASSWORD="SYS"
```

For another server, use its credentials and SuperServer port, usually `1972`.

```python
import os
import pandas as pd
from iristool import IRIStool

connection = {
    "host": os.getenv("IRIS_HOST", "localhost"),
    "port": int(os.getenv("IRIS_PORT", "1972")),
    "namespace": os.getenv("IRIS_NAMESPACE", "USER"),
    "username": os.environ["IRIS_USER"],
    "password": os.environ["IRIS_PASSWORD"],
}

people = pd.DataFrame({
    "Name": ["Ada", "Grace"],
    "Age": [36, 40],
})

with IRIStool(**connection) as db:
    db.df_to_table(people, "People")
    result = db.fetch("SELECT Name, Age FROM SQLUser.People ORDER BY Age")
    print(result)
```

This creates `SQLUser.People` and inserts two rows. The connection closes when the `with` block ends. A second run raises an error because the table exists; choose an existing-table policy below to make repeated imports explicit.

`USER` is the IRIS **namespace** selected when connecting. `SQLUser` is the default SQL **schema** used by the table helpers. Pass `table_schema` separately from the table name.

## Examples

The following examples reuse the `connection` dictionary from the quick start.

### Import a CSV

```python
with IRIStool(**connection) as db:
    db.df_to_table(pd.read_csv("people.csv"), "PeopleCSV", batch_size=1000)
```

Pandas reads the file; iristool creates the table and inserts its contents. The entire DataFrame must fit in memory. `batch_size` limits the number of rows sent to IRIS per batch, rather than streaming the input file.

### Control types and keys

```python
sales = pd.DataFrame({
    "Order Number": [1, 2],
    "Customer": ["Ada", "Grace"],
    "Total": [19.50, 42.00],
})

with IRIStool(**connection) as db:
    db.df_to_table(
        sales,
        "Sales",
        column_types={
            "Order_Number": "INT",
            "Customer": "VARCHAR(100)",
            "Total": "DECIMAL(12,2)",
        },
        primary_key="Order_Number",
        indices=[{"column": "Customer", "type": "index"}],
    )
```

When supplied, `column_types` must cover **every DataFrame column**. Its keys can use the original or normalized names. Use explicit SQL declarations when your schema needs fixed lengths, decimal precision, or other types that inference cannot decide for you.

### Query with parameters

```python
with IRIStool(**connection) as db:
    adults = db.fetch(
        "SELECT Name, Age FROM SQLUser.People WHERE Age >= ?",
        parameters=[18],
    )
    print(adults)
```

Use `?` placeholders for values. `fetch()` returns a pandas DataFrame; a query with no rows returns an empty DataFrame.

### Insert and update rows

```python
with IRIStool(**connection) as db:
    db.insert_row("People", {"Name": "Linus", "Age": 28})
    inserted = db.insert_many("People", [
        {"Name": "Margaret", "Age": 32},
        {"Name": "Barbara", "Age": 35},
    ])
    updated = db.update("People", {"Age": 37}, filters={"Name": "Ada"})
    print(inserted, updated)
```

`insert_many()` and `update()` return affected row counts. Each mutating helper commits its own successful operation and rolls back on failure; the connection context manager closes the connection and does not group multiple helper calls into one transaction.

### Inspect a table

```python
with IRIStool(**connection) as db:
    print(db.table_exists("People"))
    print(db.describe_table("People"))
    print(db.show_namespace_tables(table_schema="SQLUser"))
```



## Import behavior



### Existing tables


| Options passed to `df_to_table()`    | Behavior when the table exists                       |
| ------------------------------------ | ---------------------------------------------------- |
| Default options                      | Raise an error                                       |
| `exist_ok=True`                      | Skip the import and keep existing data               |
| `exist_ok=True, drop_if_exists=True` | Drop the table, recreate it, and import the new data |


Replacement deletes the previous table and its data. Set `drop_related_views=True` only when you also want dependent views removed. To add rows to an existing table, use `insert_row()` or `insert_many()`; `df_to_table()` does not append.

### Inferred SQL types


| DataFrame values or dtype                      | Inferred IRIS type                             |
| ---------------------------------------------- | ---------------------------------------------- |
| Boolean                                        | `BIT`                                          |
| Integers within the signed 32-bit range        | `INT`                                          |
| Larger integers within the signed 64-bit range | `BIGINT`                                       |
| Integers outside the signed 64-bit range       | `DECIMAL(20,0)`                                |
| Floating point                                 | `DOUBLE`                                       |
| Datetimes                                      | `DATETIME`; midnight-only values become `DATE` |
| Datetimes all dated January 1, 1970            | `TIME`, unless the midnight rule applies       |
| Python `date` / `time` values                  | `DATE` / `TIME`                                |
| Text up to 255 characters                      | `VARCHAR(255)`                                 |
| Longer text                                    | `CLOB`                                         |
| All-null object column                         | `VARCHAR(255)`                                 |


Nullable numeric and Boolean columns retain their dtype during inference. `None`, `pd.NA`, `NaN`, and `NaT` are inserted as SQL `NULL`. An empty DataFrame with named columns creates an empty table.

For object columns, inference recognizes dates/times or falls back to text length. Convert mixed values and structured objects before insertion. Normalize timezone-aware timestamps to the intended timezone and remove timezone information before importing.

### Names and transactions

- DataFrame column names are trimmed; spaces and dots become underscores: `Total Sales` → `Total_Sales`.
- Identifiers must start with an ASCII letter and contain only ASCII letters, digits, or underscores. Column names that collide after normalization, including case differences, are rejected.
- Pass `"People"` and `table_schema="SQLUser"` separately, rather than `"SQLUser.People"` as a table name. Avoid SQL reserved words for table/schema names.
- All insertion batches from a DataFrame share one insertion transaction. If any row fails, the inserted rows are rolled back.
- Table creation and replacement are committed before insertion. A failed import can leave an empty new table; replacement is **not atomic**.
- SQL queries, type declarations, and constraints are SQL supplied by the caller. Row values use bound parameters.

`fetch()` uses pandas' normal dtype inference. A result containing large integers and nulls may become a floating-point column; select or cast appropriately when exact integer representation in the returned DataFrame matters.

## API reference

Most table helpers default to `table_schema="SQLUser"`. See the method docstrings for complete signatures and options.


| Method                                                   | Purpose                                             |
| -------------------------------------------------------- | --------------------------------------------------- |
| `df_to_table(df, table_name, ...)`                       | Create a table and import a DataFrame               |
| `fetch(sql, parameters=None)`                            | Return query results as a DataFrame                 |
| `insert_row(table_name, values)`                         | Insert one dictionary of values                     |
| `insert_many(table_name, rows)`                          | Insert dictionaries in a batch                      |
| `update(table_name, new_values, filters)`                | Update matching rows                                |
| `update_many(table_name, updates)`                       | Apply a list of `(new_values, filters)` pairs       |
| `create_table(table_name, columns, ...)`                 | Create a table from SQL type declarations           |
| `add_columns(table_name, new_columns)`                   | Add columns to an existing table                    |
| `drop_table(table_name, ...)`                            | Drop a table, or a view with `view_or_table="view"` |
| `table_exists(table_name)`                               | Check whether a table or view exists                |
| `describe_table(table_name)`                             | Return column and index metadata                    |
| `create_index(index_name, table_name, column_name, ...)` | Create an index                                     |
| `index_exists(table_name, index_name)`                   | Check index metadata                                |
| `create_view(view_name, sql, ...)`                       | Create a SQL view                                   |
| `views_using_table(table_name)`                          | List dependent views                                |
| `show_namespace_tables(...)`                             | List tables, with optional name/schema filters      |
| `show_namespace_schemas()`                               | List schemas containing base tables                 |
| `close()`                                                | Close the connection explicitly                     |




## Development and testing

Use [uv](https://docs.astral.sh/uv/getting-started/installation/) with Python 3.10 or newer. `uv run` prepares the project environment and runs Python; `unittest` is the test runner. No virtual-environment activation is needed.

```bash
uv run python -m unittest discover -s tests -v -b
```

The regular suite runs unit tests and skips live database tests. `-v` shows each test and its result. `-b` buffers output from passing tests, hiding expected error messages; if a test fails, its captured output is displayed.

### Run against Docker IRIS

```bash
docker compose up -d --build
docker compose logs --tail 20
# Wait until IRIS reports that it has started.
IRIS_INTEGRATION=1 uv run python -m unittest discover -s tests -v -b
```

The included development server uses:


| Setting                | Value                                                        |
| ---------------------- | ------------------------------------------------------------ |
| SQL connection         | `localhost:9091`                                             |
| Management Portal      | [localhost:9092](http://localhost:9092/csp/sys/UtilHome.csp) |
| Namespace              | `USER`                                                       |
| Development account    | `_SYSTEM` / `SYS`                                            |
| Durable database files | `storage/`                                                   |


Live tests read the `IRIS_HOST`, `IRIS_PORT`, `IRIS_NAMESPACE`, `IRIS_USER`, and `IRIS_PASSWORD` variables, with the above defaults. They create uniquely named test tables/views and remove them after each test. The startup script unexpires development passwords.

On PowerShell, set `$env:IRIS_INTEGRATION = "1"`, then run the same `uv run` command without the `IRIS_INTEGRATION=1` prefix.

Expected result: `Ran 22 tests` followed by `OK`, with no skipped tests. Some tests deliberately attempt a duplicate table or primary key to verify that errors propagate and inserted rows roll back. Their error messages are expected, not failed tests. Unit-test names such as `SQLUser.Data` refer to mocked operations and do not create real tables.

### Inspect sample data in the IRIS Portal

The automated tests clean up their tables, so they leave nothing to browse. To see a lasting example, keep IRIS running and execute:

```bash
uv run python examples/portal_demo.py
```

This imports three rows, verifies names, nulls, and Unicode, prints the result, and **leaves** `SQLUser.IRISTool_Demo` **in IRIS**. Each run replaces that demo table and its previous data. It uses the same connection environment variables and defaults as the tests.

Open the [Management Portal](http://localhost:9092/csp/sys/UtilHome.csp), navigate to **System Explorer → SQL**, select namespace **USER** (or your configured `IRIS_NAMESPACE`), and execute:

```sql
SELECT Sample_Number, Name, Score, Active, Note
FROM SQLUser.IRISTool_Demo
ORDER BY Sample_Number;
```

You should see Ada, Grace, and Linus, including a missing score and a missing Boolean value. To remove the demo, execute `DROP TABLE SQLUser.IRISTool_Demo;` in the SQL page. When finished, run `docker compose stop`; the demo data persists in `storage/` when IRIS is restarted.

Coverage includes mixed DataFrame types, nulls, Unicode and long text, large integers, batching, empty imports, replacement, row helpers, metadata, ordinary indexes/views, and rollback after constraint failures. 

## Troubleshooting


| Symptom                                 | What to check                                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `pip install iristool` finds no package | Before the first PyPI release, install the source checkout with `python -m pip install .`              |
| Connection refused                      | Check that IRIS is running and the SuperServer port is reachable; this Compose setup maps it to `9091` |
| Authentication failure                  | Check the account, password, namespace access, and password expiration                                 |
| Table already exists                    | Choose skip/replacement explicitly, or use row helpers to insert into it                               |
| Invalid identifier or colliding columns | Rename columns before importing; follow the naming rules above                                         |
| Constraint failure in a batch           | Correct the offending data; inserted rows roll back, but the created table remains                     |
| Timezone-aware datetime rejected        | Convert to the desired timezone, then remove timezone information                                      |




## Project layout

```text
.
├── src/iristool/
│   ├── __init__.py         Public IRIStool import
│   └── core.py             DataFrame and SQL helpers
├── tests/
│   ├── test_iristool.py    Unit tests
│   └── test_iris_integration.py  Opt-in live IRIS tests
├── docs/
│   └── publish.md          PyPI release instructions using uv
├── examples/
│   └── portal_demo.py      Persistent sample table for Portal inspection
├── pyproject.toml         Package metadata and build configuration
├── requirements.txt       Runtime dependencies for pip
├── Dockerfile             Development IRIS image
├── docker-compose.yml     Local test server and port mappings
├── docker-entrypoint.sh   IRIS startup wrapper
├── iris.script            Development password initialization
├── .dockerignore          Docker build exclusions
├── .gitignore             Git exclusions
├── README.md
└── LICENSE
```

The Python wheel includes the library, metadata, and license. Docker files and durable database data are not part of the installed library.

## Credits and license

Created by **Pietro Di Leo**, based on the Python utilities from [iris_tool_and_data_manager](https://github.com/pietrodileo/iris_tool_and_data_manager).

Released under the **MIT License**. Copyright © 2025–2026 Pietro Di Leo.

See [LICENSE](LICENSE) for the full license text. A copy is included in both the Python wheel and source distribution.