# iristool

Load pandas DataFrames into InterSystems IRIS and query them with Python.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat)![InterSystems IRIS](https://img.shields.io/badge/InterSystems-IRIS-00a99d?style=flat)![MIT License](https://img.shields.io/badge/license-MIT-2ea043?style=flat)

**iristool** is a small Python library for moving data between pandas and InterSystems IRIS. Create a SQL table from a DataFrame, run parameterized queries, and manage rows, tables, views, and indexes through one connection object.

Python runs in your own environment and connects to an existing IRIS server through the official `intersystems-irispython` DB API. Install the library on your laptop, in a notebook, or in a Python application; no Python packages need to be installed inside IRIS.

[Installation](#installation) · [Quick start](#quick-start) · [Dataset imports](#dataset-integrations) · [CLI](#import-datasets-from-the-command-line-cli) · [Examples](#examples) · [API](#api-reference) · [Testing](#development-and-testing)

[Authentication](docs/authentication.md) · [Adding data sources](docs/DEV.md) · [Publishing](docs/publish.md)

---

## Features

<details>
<summary>What iristool does</summary>

- **DataFrame to SQL:** create a table, infer column types, and insert rows in batches.
- **SQL to DataFrame:** retrieve query results with optional bound parameters.
- **Data handling:** normalize column names and convert pandas missing values to SQL `NULL`.
- **Import control:** choose whether to fail, skip, or replace an existing table; supply explicit types, a primary key, constraints, and indexes.
- **SQL helpers:** insert and update rows, inspect metadata, and manage tables, columns, views, and indexes.
- **Small dependency list:** pandas and the official InterSystems Python SDK.

Optional [dataset integrations](#dataset-integrations) download Kaggle and Hugging Face datasets and import them through the same DataFrame API. Source libraries are installed only when requested.

The library handles the IRIS part of a data workflow. Read a CSV with pandas, download data with another library, or construct a DataFrame yourself, then pass it to `df_to_table()`.

</details>

## Installation

### Requirements

- Python **3.10 or newer**, on a platform supported by the InterSystems SDK.
- A reachable **InterSystems IRIS 2022.1 or newer** server supporting the Python DB API.
- An IRIS account with SQL permissions for the operations you need.

### With pip

```bash
python -m pip install iristool
```

### With uv

In your own uv project:

```bash
uv add iristool
```

For Kaggle or Hugging Face support, select an extra as shown in
[dataset integrations](#dataset-integrations). Both pip and uv install the
required dependencies automatically. Import the class with:

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

## Dataset integrations

**New in 0.3.0:** download datasets directly from external sources like Kaggle or Hugging Face and save them using the same `IRIStool.df_to_table()`
implementation as a normal DataFrame import. The integrations live in
`iristool.integrations`.

### Install optional support

Install from PyPI with pip, choosing the sources you need:

```bash
python -m pip install 'iristool[kaggle]>=0.3.0'        # Kaggle
python -m pip install 'iristool[huggingface]>=0.3.0'   # Hugging Face
python -m pip install 'iristool[integrations]>=0.3.0'  # all sources + core
```

Or add iristool to your own uv project:

```bash
uv add 'iristool[kaggle]>=0.3.0'        # Kaggle
uv add 'iristool[huggingface]>=0.3.0'   # Hugging Face
uv add 'iristool[integrations]>=0.3.0'  # all sources + core
```

Choose one command from either group. Every extra includes the core library. Using only `pip install iristool` or `uv add iristool` will install the core package without source SDKs.

If you use uv without a project, run `uv venv`, then  
`uv pip install 'iristool[integrations]>=0.3.0'` to install into that environment.

### Import datasets from Python

<details>
<summary>Show instructions</summary>

This example downloads the Iris dataset from [Kaggle (`uciml/iris`)](https://www.kaggle.com/datasets/uciml/iris)
and [Hugging Face (`scikit-learn/iris`)](https://huggingface.co/datasets/scikit-learn/iris),
importing each into its own IRIS table.

Start the included IRIS server with `docker compose up -d --build`, then run:

```python
from iristool import IRIStool
from iristool.integrations import import_kaggle, import_huggingface

with IRIStool(host="localhost", port=9091, namespace="USER",
              username="_SYSTEM", password="SYS") as db:
    import_kaggle(db, "uciml/iris", table="KaggleIris")
    import_huggingface(db, "scikit-learn/iris", table="HFIris")
    print(db.fetch("SELECT COUNT(*) AS RowsLoaded FROM SQLUser.HFIris"))
    print(db.describe_table("HFIris"))
```

Each example imports 150 rows. The helpers return a mapping such as
`{"SQLUser.HFIris": 150}` and print the imported table and row count.
The caller owns the connection: the integrations neither open nor close it.
Use the same `db` afterwards for queries, metadata, indexes, or other imports.
These samples use this repository's Docker port **9091**; an ordinary IRIS
installation usually listens on **1972**.

You can also import from `iristool.integrations.kaggle` or
`iristool.integrations.huggingface`; each module exposes `import_dataset(db, ...)`.

</details>

### Import datasets from the command line (CLI)

<details>
<summary>Show instructions</summary>

The CLI lets you download a dataset and save it to IRIS from your terminal,
without writing a Python script. `kaggle-iris` imports Kaggle datasets;
`hf-iris` imports Hugging Face datasets. Both use iristool's DataFrame import
and SQL type inference.

**1. Install the source support** using the pip or uv commands under
[Install optional support](#install-optional-support).

**2. Start IRIS and set its connection details.** For this repository's Docker
server, run `docker compose up -d --build` from the checkout and wait for IRIS
to start. Then set these variables in bash/zsh:

```bash
export IRIS_HOST=localhost
export IRIS_PORT=9091
export IRIS_NAMESPACE=USER
export IRIS_USER=_SYSTEM
export IRIS_PASSWORD=SYS
```

For your own server, use its address, SQL port, namespace, and credentials.
The defaults when variables are omitted are `localhost:1972`, namespace `USER`,
and `_SYSTEM` / `SYS`.

**3. Run the import.** With pip and an activated virtual environment:

```bash
kaggle-iris uciml/iris --file Iris.csv --table KaggleIris
hf-iris scikit-learn/iris --table HFIris
```

If you installed with `uv add` in your own project, run:

```bash
uv run kaggle-iris uciml/iris --file Iris.csv --table KaggleIris
uv run hf-iris scikit-learn/iris --table HFIris
```

Each command downloads the data, creates its target table in `SQLUser`, and
prints the imported row count. These examples normally need no source login;
for private or gated data, follow the [authentication guide](docs/authentication.md).

An existing table causes an error. Add `--replace` only when you want to
**delete the existing table and its data**, then import again.
Use `kaggle-iris --help` or `hf-iris --help` to list available options.

When developing inside the iristool checkout, use `uv run --all-extras` in
place of `uv run` to include its optional source dependencies. The CLI opens
and closes the IRIS connection; Python imports use the connection you pass.

</details>

### Kaggle datasets

<details>
<summary>Show instructions</summary>

Browse [Kaggle datasets](https://www.kaggle.com/datasets), open a dataset, and
copy its `owner/dataset` ID or its `https://www.kaggle.com/datasets/...` page URL.
The integration downloads and extracts the data automatically through KaggleHub.
Public datasets such as `uciml/iris` usually work without login. For private or
consent-required data, follow the [Kaggle authentication guide](docs/authentication.md#kaggle).

Every CSV/TSV is imported into its own table; other file types are ignored.
Default table names come from file stems (`Iris.csv` → `SQLUser.Iris`).
Select one file by its case-sensitive path from Kaggle's Data Explorer:

```bash
uv run kaggle-iris uciml/iris --file Iris.csv --table Flowers
uv run kaggle-iris uciml/iris/versions/2 --file Iris.csv --table Flowers --replace
```

`--table` requires one file. Without `--file`, KaggleHub downloads the whole
dataset; with it, only the requested file is downloaded. Downloads are cached
in `~/.cache/kagglehub`; `KAGGLEHUB_CACHE` changes the cache location.

For CSV parsing control in Python, pass pandas options directly:

```python
with IRIStool(**connection) as db:
    import_kaggle(db, "owner/dataset", file="sales.csv", read_csv_kwargs={
        "dtype": {"postal_code": "string"},
        "parse_dates": ["order_date"],
        "encoding": "utf-8",
    })
```

Here `connection` is the dictionary from the quick start. Do not pass pandas
iterator/chunk options: this version imports complete DataFrames.

</details>

### Hugging Face datasets

<details>
<summary>Show instructions</summary>

Browse [Hugging Face datasets](https://huggingface.co/datasets), open one, and
copy its repository ID or `https://huggingface.co/datasets/...` page URL.
The integration uses `datasets.load_dataset(...).to_pandas()`, then calls
`db.df_to_table()`. It imports one split per call; the default split is `train`.
The datasets library handles supported underlying formats such as CSV, JSON,
and Parquet. No manual file download or unzipping is needed.

Public, ungated datasets such as `scikit-learn/iris` work without login. For
private or gated data, follow the [Hugging Face authentication guide](docs/authentication.md#hugging-face).

Choose the **subset/configuration** and **split** shown in the dataset viewer:

```bash
uv run hf-iris scikit-learn/iris --split 'train[:10]' --table HFSample
# For a dataset with named configurations:
uv run hf-iris stanfordnlp/sst2 --config default --split validation --table Sentiment
```

Use `--revision TAG_OR_COMMIT` to pin a dataset revision. A split slice limits
rows imported into IRIS; the loader may still download/prepare the full source.
Datasets without a `train` split require `--split`. Datasets with multiple
configurations may require `--config`.

The default table is `HF_<dataset>_[<config>_]<split>`, with punctuation replaced
by underscores. For `scikit-learn/iris`, this is `SQLUser.HF_iris_train`.
Use `--table` to choose a short explicit name, particularly for sliced splits.
Class-label features keep the values returned by `to_pandas()` (often integer
codes); the integration does not convert them into human-readable label names.

</details>

### Options and behavior

<details>
<summary>Show instructions</summary>

| Option / Python argument        | Kaggle                             | Hugging Face                 |
| ------------------------------- | ---------------------------------- | ---------------------------- |
| `--table` / `table`             | One file's target table            | Target split's table         |
| `--schema` / `schema`           | SQL schema, default `SQLUser`      | Same                         |
| `--replace` / `replace=True`    | Drop and recreate existing targets | Same                         |
| `--file` / `file`               | Relative CSV/TSV path              | —                            |
| `read_csv_kwargs` (Python only) | Options passed to pandas           | —                            |
| `--split` / `split`             | —                                  | Split/slice, default `train` |
| `--config` / `config`           | —                                  | Configuration/subset         |
| `--revision` / `revision`       | Version is part of dataset ID      | Branch, tag, commit          |


`USER` is the connection namespace; `SQLUser` is the SQL schema. The connection
account needs SQL permissions, and a custom schema must be usable by that account.
Identifiers use ASCII letters/digits/underscores and must start with a letter.
Imported column names replace punctuation with underscores; a `Data_` prefix is
added when needed. Colliding names fail rather than silently overwriting columns.

Pandas determines DataFrame dtypes; the core's [inferred SQL types](#inferred-sql-types)
apply unchanged. Dates in CSV remain text unless parsed. Leading zeros can be
lost with default CSV inference; specify `dtype` when they matter.
For custom SQL types, constraints, keys, or batch sizes, download/prepare a
DataFrame and call `db.df_to_table()` directly with its existing options.

</details>

### Dataset limitations

<details>
<summary>Show instructions</summary>

- Each CSV/TSV file or Hugging Face split must fit in memory. Database batching
does not stream source data. Hugging Face streaming imports are not implemented.
- Hugging Face nested/list/media columns are rejected before any table write.
Flatten or explicitly serialize them yourself, then use `df_to_table()`.
- Kaggle competitions, append mode, and other source connectors are not included.
- Multi-file imports stop on the first error; earlier imported tables remain.
Row insertion rolls back on failure, but DDL/replacement commits separately.
A failure can leave an empty new table; replacement cannot recover old data.
- Missing source library: install the matching extra and include it in `uv run`.
- HTTP 401/403 or gated repository: follow the [authentication guide](docs/authentication.md) and check dataset access/accepted terms.
- Missing split/configuration: select names shown in the Hugging Face viewer.
- Connection refused: check Docker logs, the SuperServer port, and `IRIS_*` settings.
- Existing table: choose a different name or explicitly replace it.

</details>

## Examples

<details>
<summary>Python examples</summary>

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

</details>

## Import behavior

<details>
<summary>Table policies, inferred SQL types, and transactions</summary>

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

</details>

## API reference

<details>
<summary>Available methods</summary>

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

</details>

## Development and testing

<details>
<summary>Local setup, Docker, and test commands</summary>

To add another dataset source, follow the [integration development guide](docs/DEV.md).

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

Source-specific live tests remain skipped unless enabled separately; for more information see [dataset integration tests](#test-the-integrations).

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

### Test the integrations

From this `iristool` folder, run the suite with both extras installed:

```bash
uv run --all-extras python -m unittest discover -s tests -v -b
```

Unit tests use mocked downloads/connections and real pandas DataFrames. Tests
also check missing optional dependencies and preservation of numeric/null values.
Without extras, source-specific unit tests are skipped and core tests still run.

For all core and source integration tests against the bundled Docker IRIS:

```bash
docker compose up -d --build
# Wait until IRIS has started, then:
IRIS_PORT=9091 IRIS_INTEGRATION=1 KAGGLE_IRIS_INTEGRATION=1 HF_IRIS_INTEGRATION=1 \
  uv run --all-extras python -m unittest discover -s tests -v -b
```

The source tests require internet access, download the public Iris dataset from
each provider, verify **150 rows** and inferred integer/double/text SQL types,
and remove their uniquely named test tables. No source token is normally needed.
Enable only `KAGGLE_IRIS_INTEGRATION=1` or `HF_IRIS_INTEGRATION=1` to test one provider.
On PowerShell, set the environment variables with `$env:NAME = "value"` before
running the same Python test command without the inline assignments.

</details>

## Troubleshooting

<details>
<summary>Common problems and solutions</summary>

| Symptom                                 | What to check                                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Integrations missing after pip install  | Install iristool 0.3.0 or newer with the desired source extra                                          |
| Connection refused                      | Check that IRIS is running and the SuperServer port is reachable; this Compose setup maps it to `9091` |
| Authentication failure                  | Check the account, password, namespace access, and password expiration                                 |
| Table already exists                    | Choose skip/replacement explicitly, or use row helpers to insert into it                               |
| Invalid identifier or colliding columns | Rename columns before importing; follow the naming rules above                                         |
| Constraint failure in a batch           | Correct the offending data; inserted rows roll back, but the created table remains                     |
| Timezone-aware datetime rejected        | Convert to the desired timezone, then remove timezone information                                      |

</details>

## Project layout

<details>
<summary>Repository files</summary>

```text
.
├── src/iristool/
│   ├── __init__.py         Public IRIStool import
│   ├── core.py             DataFrame and SQL helpers
│   └── integrations/       Optional Kaggle / Hugging Face downloads and CLI
├── tests/
│   ├── test_iristool.py    Unit tests
│   └── test_iris_integration.py  Opt-in live IRIS tests
├── docs/
│   ├── authentication.md   Kaggle and Hugging Face login and tokens
│   ├── DEV.md              Guide to adding dataset sources
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

</details>

## Credits and license

Created by **Pietro Di Leo**, based on the Python utilities from [iris_tool_and_data_manager](https://github.com/pietrodileo/iris_tool_and_data_manager).

Released under the **MIT License**. Copyright © 2025–2026 Pietro Di Leo.

See [LICENSE](LICENSE) for the full license text. A copy is included in both the Python wheel and source distribution.
