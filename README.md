# iristool

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat)![InterSystems IRIS](https://img.shields.io/badge/InterSystems-IRIS-00a99d?style=flat)![MIT License](https://img.shields.io/badge/license-MIT-2ea043?style=flat)

**iristool** is a small Python library for moving data between pandas and InterSystems IRIS. Create a SQL table from a DataFrame, run parameterized queries, and manage rows, tables, views, and indexes through one connection object.

Python runs in your own environment and connects to an existing IRIS server through the official `intersystems-irispython` DB API. Install the library on your laptop, in a notebook, or in a Python application; no Python packages need to be installed inside IRIS.

[Installation](#installation) · [Quick start](#quick-start) · [Dataset imports](#dataset-integrations) · [CLI](#import-datasets-from-the-command-line-cli) · [Export](#export-a-table) · [Examples](#examples) · [API](#api-reference) · [Testing](#development-and-testing)

[Authentication](docs/authentication.md) · [Adding data sources](docs/DEV.md) · [Publishing](docs/publish.md)

---



## Features

What iristool does

- **DataFrame to SQL:** create a table, infer column types, and insert rows in batches.
- **SQL to DataFrame:** retrieve query results with optional bound parameters.
- **Table export:** save a table as CSV, XLSX, or JSON through pandas.
- **Data handling:** normalize column names and convert pandas missing values to SQL `NULL`.
- **Import control:** choose whether to fail, skip, or replace an existing table; supply explicit types, a primary key, constraints, and indexes.
- **SQL helpers:** insert and update rows, inspect metadata, and manage tables, columns, views, and indexes.
- **Small dependency list:** pandas and the official InterSystems Python SDK.

Optional [dataset integrations](#dataset-integrations) download Kaggle and Hugging Face datasets and import them through the same DataFrame API. Source libraries are installed only when requested.

The library handles the IRIS part of a data workflow. Read a CSV with pandas, download data with another library, or construct a DataFrame yourself, then pass it to `df_to_table()`.

## Supported import and export formats


| Operation                        | Supported input or output                                                                              | How it works                                                                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Core import                      | pandas `DataFrame`                                                                                     | `db.df_to_table(df, "Table")`; the core receives a DataFrame, not a file path                                                       |
| Local file import through pandas | CSV, TSV, XLSX, JSON, Parquet, and other formats pandas can read                                       | Read the file with pandas first, then pass the resulting DataFrame to `df_to_table()`; some readers require additional dependencies |
| Kaggle import                    | **CSV (**`.csv`**) and TSV (**`.tsv`**) only**                                                         | `import_kaggle()` / `iristool-kaggle`; other file types in a downloaded dataset are ignored                                         |
| Hugging Face import              | Dataset splits loadable by `datasets.load_dataset()`, including tabular CSV, JSON, and Parquet sources | `import_huggingface()` / `iristool-hf`; the split must convert to a DataFrame with SQL-compatible scalar columns                    |
| Core export                      | **CSV (**`.csv`**), Excel (**`.xlsx`**), JSON (**`.json`**)**                                          | `db.export_table("Table", "output.csv")`; the extension selects the pandas writer                                                   |


CSV/JSON export needs only the base installation. XLSX import through pandas
and XLSX export require the optional `excel` extra (`openpyxl`). Parquet
import through pandas requires a compatible engine such as `pyarrow`, installed
separately or provided by the Hugging Face dependencies.

Nested JSON objects, lists, images, and audio need preprocessing into scalar columns before SQL import and are not directly supported. JSON export defaults to an array of row objects. 

Direct `export_table()` output is limited to the three extensions above:
`.tsv`, `.xls`, and `.parquet` are not accepted. For other export formats,
retrieve a DataFrame with `db.fetch(...)` and use pandas directly.

See [dataset integrations](#dataset-integrations) and [export examples](#export-a-table).

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

**Standalone environment (no** `pyproject.toml` **required)**

To install from PyPI in a folder used for testing or scripts:

```bash
uv venv
source .venv/bin/activate
uv pip install iristool
# Or install the core plus both dataset sources:
# uv pip install 'iristool[integrations]>=0.3.1'
```

**Application project (with** `pyproject.toml`**)**

In a separate uv project that depends on iristool:

```bash
uv add iristool
```

This records the dependency in the application's `pyproject.toml` and lockfile.
If starting a new application project, run `uv init` first.

**Local iristool source development**

If you cloned this repository, inside the cloned iristool source folder run: 

```bash
uv sync                 # core only; creates or updates the local .venv
# uv sync --all-extras  # include both dataset sources and Excel support
```

This installs the local source for development, rather than testing the PyPI
release. Do not run `uv add iristool` in this folder: a project cannot depend on itself. 

See [DEV.md](docs/DEV.md) for source-development instructions.

For Kaggle or Hugging Face support, select an extra as shown in [dataset integrations](#dataset-integrations). Both pip and uv install the  
required dependencies automatically. 

Import the class with:

```python
from iristool import IRIStool
```



## Quick start



### Configure and load `.env`

Create a `.env` file in the folder where you run your scripts or CLI commands.
If you cloned this repository, copy the [template](.env.example) once:

```bash
cp .env.example .env
```

If you installed from PyPI, create `.env` yourself with the same settings:

```dotenv
IRIS_HOST=localhost
IRIS_PORT=9091
IRIS_NAMESPACE=USER
IRIS_USER=_SYSTEM
IRIS_PASSWORD=SYS
# Optional source tokens; uncomment only when needed:
KAGGLE_API_TOKEN='your-kaggle-token'
HF_TOKEN='your-hugging-face-read-token'
```

These connection settings match the repository's Docker development server. 

For your own IRIS server, change the credentials, namespace, and SQL port. 

See [authentication](docs/authentication.md) for obtaining data source tokens.

**Load** `.env` **before running any example or import** in this terminal (bash/zsh):

```bash
set -a
source .env
set +a
```

This exports the settings to Python and CLI processes, including any uncommented
source tokens. Repeat the loading step in each new terminal and after editing
`.env`. iristool does not read the file automatically.

### Import a DataFrame

After loading `.env`, run:

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

Download datasets directly from external sources like Kaggle or Hugging Face and save them using the same `IRIStool.df_to_table()` implementation as a normal DataFrame import. 

The integrations live in `iristool.integrations`.

### Install optional support

Follow [Installation](#installation), replacing `iristool` with the package specification for the sources you need:


| Sources          | Package specification    |
| ---------------- | ------------------------ |
| Kaggle           | `iristool[kaggle]`       |
| Hugging Face     | `iristool[huggingface]`  |
| All data sources | `iristool[integrations]` |


For example: `uv pip install 'iristool[integrations]>=0.3.1'` or
`python -m pip install 'iristool[integrations]>=0.3.1'`. Every extra includes the core library.

**Datasets used in the examples**


| Dataset                                                                                                                                | Source       | IRIS table names used below                                                       |
| -------------------------------------------------------------------------------------------------------------------------------------- | ------------ | --------------------------------------------------------------------------------- |
| [Iris —](https://www.kaggle.com/datasets/uciml/iris) `uciml/iris` ([version 2](https://www.kaggle.com/datasets/uciml/iris/versions/2)) | Kaggle       | `KaggleIris`, `Flowers`, `FlowersTextID`; default `Iris`                          |
| [Iris —](https://huggingface.co/datasets/scikit-learn/iris) `scikit-learn/iris`                                                        | Hugging Face | `HFIris`, `HFSample`, `IrisSample`; default `HF_iris_train`                       |
| [SST-2 —](https://huggingface.co/datasets/stanfordnlp/sst2) `stanfordnlp/sst2`                                                         | Hugging Face | `Sentiment`                                                                       |
| [Brazilian E-Commerce —](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) `olistbr/brazilian-ecommerce`                    | Kaggle       | One table per CSV, including `olist_orders_dataset` and `olist_customers_dataset` |


These are the source dataset pages. SQL table names are local names chosen by
iristool or by `--table`.

### Import datasets from Python

This example downloads the Iris dataset from [Kaggle (](https://www.kaggle.com/datasets/uciml/iris)`uciml/iris`[)](https://www.kaggle.com/datasets/uciml/iris)
and [Hugging Face (](https://huggingface.co/datasets/scikit-learn/iris)`scikit-learn/iris`[)](https://huggingface.co/datasets/scikit-learn/iris),
importing each into its own IRIS table.

Use a running IRIS server and [configure and load](#configure-and-load-env) `.env`
in the terminal where you launch Python. For the repository's development server,
start IRIS with `docker compose up -d --build` first. Then run:

```python
import os
from iristool import IRIStool
from iristool.integrations import import_kaggle, import_huggingface

with IRIStool(
    host=os.environ["IRIS_HOST"],
    port=int(os.environ["IRIS_PORT"]),
    namespace=os.environ["IRIS_NAMESPACE"],
    username=os.environ["IRIS_USER"],
    password=os.environ["IRIS_PASSWORD"],
) as db:
    import_kaggle(db, "uciml/iris", table="KaggleIris")
    import_huggingface(db, "scikit-learn/iris", table="HFIris")
    print(db.fetch("SELECT COUNT(*) AS RowsLoaded FROM SQLUser.HFIris"))
    print(db.describe_table("HFIris"))
```

Each example imports 150 rows. The helpers return a mapping such as
`{"SQLUser.HFIris": 150}` and print the imported table and row count.
The caller owns the connection: the integrations neither open nor close it.
Use the same `db` afterwards for queries, metadata, indexes, or other imports.

You can also import from `iristool.integrations.kaggle` or
`iristool.integrations.huggingface`; each module exposes `import_dataset(db, ...)`.

### Import datasets from the command line (CLI)

The CLI lets you download a dataset and save it to IRIS from your terminal,
without writing a Python script. 

`iristool-kaggle` imports Kaggle datasets; `iristool-hf` imports Hugging Face datasets. 

Both use iristool's DataFrame import and SQL type inference.

**1. Install the source support** using the pip or uv commands under
[Install optional support](#install-optional-support).

**2. Configure and load** `.env`**.** Follow the [setup instructions](#configure-and-load-env)
to create the file with your IRIS settings and optional source tokens. Make sure
IRIS is running; for the repository's Docker server, use
`docker compose up -d --build` and wait for startup. In the terminal where you
will run the imports, load `.env` (bash/zsh):

```bash
set -a
source .env
set +a
```

The CLI reads `IRIS_*` from the environment. KaggleHub reads
`KAGGLE_API_TOKEN` and Hugging Face reads `HF_TOKEN` when those tokens are set.
If IRIS settings are omitted, the CLI defaults to `localhost:1972`, namespace
`USER`, and `_SYSTEM` / `SYS`.

**3. Run the import.** After activating the environment installed with pip or
`uv pip install`, use the CLI directly:

```bash
iristool-kaggle uciml/iris --file Iris.csv --table KaggleIris
iristool-hf scikit-learn/iris --table HFIris
```

If you installed with `uv add` in your own project, run:

```bash
uv run iristool-kaggle uciml/iris --file Iris.csv --table KaggleIris
uv run iristool-hf scikit-learn/iris --table HFIris
```

Each command downloads the data, creates its target table in `SQLUser`, and
prints the imported row count. These examples normally need no source login;
for private or gated data, follow the [authentication guide](docs/authentication.md).

An existing table causes an error. Add `--replace` only when you want to
**delete the existing table and its data**:

```bash
iristool-kaggle uciml/iris --file Iris.csv --table KaggleIris --replace
iristool-hf scikit-learn/iris --table HFIris --replace
```

Show all available options without importing data:

```bash
iristool-kaggle --help
iristool-hf --help
```



### Kaggle datasets

Browse [Kaggle datasets](https://www.kaggle.com/datasets), open a dataset, and
copy its `owner/dataset` ID or its `https://www.kaggle.com/datasets/...` page URL.
The integration downloads and extracts the data automatically through KaggleHub.
Public datasets such as `uciml/iris` usually work without login. For private or
consent-required data, follow the [Kaggle authentication guide](docs/authentication.md#kaggle).

Every CSV/TSV is imported into its own table; other file types are ignored.
Default table names come from file stems (`Iris.csv` → `SQLUser.Iris`).
Select one file by its case-sensitive path from Kaggle's Data Explorer:

```bash
iristool-kaggle uciml/iris --file Iris.csv --table Flowers
iristool-kaggle uciml/iris/versions/2 --file Iris.csv --table Flowers --replace
```

`--table` requires one file. Without `--file`, KaggleHub downloads the whole
dataset; with it, only the requested file is downloaded. Downloads are cached
in `~/.cache/kagglehub`; the **environment variable** `KAGGLEHUB_CACHE` changes
the cache location (for example, `export KAGGLEHUB_CACHE="$HOME/dataset-cache"`).

Example: import every CSV in a Kaggle dataset

The [Olist dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) contains several CSV files. Load `.env`, then omit both `--file` and `--table`:

```bash
iristool-kaggle olistbr/brazilian-ecommerce
```

iristool imports every CSV/TSV into its own table in `SQLUser`, including:


| Downloaded file                 | Target table                        |
| ------------------------------- | ----------------------------------- |
| `olist_orders_dataset.csv`      | `SQLUser.olist_orders_dataset`      |
| `olist_customers_dataset.csv`   | `SQLUser.olist_customers_dataset`   |
| `olist_order_items_dataset.csv` | `SQLUser.olist_order_items_dataset` |


The remaining CSVs are imported too; non-CSV/TSV files are ignored. 

The Python equivalent, using the quick-start connection, is:

```python
with IRIStool(**connection) as db:
    imported = import_kaggle(db, "olistbr/brazilian-ecommerce")
    print(imported)  # {"SQLUser.olist_customers_dataset": row_count, ...}
```

To import only orders, use `iristool-kaggle olistbr/brazilian-ecommerce --file olist_orders_dataset.csv --table Orders`. Existing targets cause an error; `--replace` deletes and recreates them. Imports across several tables are not atomic: if a later file fails, earlier imports remain. Each CSV is loaded into memory separately. No foreign keys are inferred between these tables.

For CSV parsing control in Python, pass pandas options directly:

```python
with IRIStool(**connection) as db:
    import_kaggle(db, "olistbr/brazilian-ecommerce", file="olist_orders_dataset.csv", read_csv_kwargs={
        "dtype": {"customer_id": "string"},
        "parse_dates": ["order_purchase_timestamp"],
        "encoding": "utf-8",
    })
```

Here `connection` is the dictionary from the quick start. Do not pass pandas iterator/chunk options: this version imports complete DataFrames.

### Hugging Face datasets

Browse [Hugging Face datasets](https://huggingface.co/datasets), open one, and copy its repository ID or `https://huggingface.co/datasets/...` page URL. The integration uses `datasets.load_dataset(...).to_pandas()`, then calls `db.df_to_table()`. It imports one split per call; the default split is `train`. 

The datasets library handles supported underlying formats such as CSV, JSON, and Parquet. No manual file download or unzipping is needed.

Public, ungated datasets such as `scikit-learn/iris` work without login. For private or gated data, follow the [Hugging Face authentication guide](docs/authentication.md#hugging-face).

**Example of a dataset requiring browser confirmation**

[LMSYS-Chat-1M (](https://huggingface.co/datasets/lmsys/lmsys-chat-1m)`lmsys/lmsys-chat-1m`[)](https://huggingface.co/datasets/lmsys/lmsys-chat-1m) requires you to sign in and accept its conditions on the dataset page. To see the access error with an account that has not received access (or without a token), load your IRIS connection settings and run:

```bash
iristool-hf lmsys/lmsys-chat-1m --split 'train[:1]' --table AccessCheck
```

The command exits with status **1** before importing any tables and reports:

```text
Import failed: Dataset processing failed: access denied. Open https://huggingface.co/datasets/lmsys/lmsys-chat-1m in your browser, sign in and confirm the terms or request access. Wait for approval if required. Then set HF_TOKEN (or log in with the source SDK) using the approved account and repeat the same command. No dataset tables were imported.
```

See [browser approval and token setup](docs/authentication.md#when-browser-approval-is-required) for the steps to resolve access errors.

This example demonstrates the access restriction. LMSYS contains nested conversation values, so approval alone does not make it ready for direct SQL import: flatten or serialize them before using `db.df_to_table()`. Once access is granted, even a one-row slice may download/prepare the full dataset. Use the Iris examples below for a small, directly importable dataset.

Choose the **subset/configuration** and **split** shown in the dataset viewer:

```bash
iristool-hf scikit-learn/iris --split 'train[:10]' --table HFSample
# For a dataset with named configurations:
iristool-hf stanfordnlp/sst2 --config default --split validation --table Sentiment
```

Use `--revision TAG_OR_COMMIT` to pin a dataset revision. A split slice limits rows imported into IRIS; the loader may still download/prepare the full source. Datasets without a `train` split require `--split`. Datasets with multiple configurations may require `--config`.

The default table is `HF_<dataset>_[<config>_]<split>`, with punctuation replaced by underscores. For `scikit-learn/iris`, this is `SQLUser.HF_iris_train`. Use `--table` to choose a short explicit name, particularly for sliced splits.
Class-label features keep the values returned by `to_pandas()` (often integer codes); the integration does not convert them into human-readable label names.

### Options and behavior


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


**CLI examples** — activate your environment and load `.env` first.

Import one Kaggle file with an explicit schema and table name:

```bash
iristool-kaggle uciml/iris --file Iris.csv --schema SQLUser --table Flowers
```

Import only the first 10 rows of a Hugging Face split from its `main` revision:

```bash
iristool-hf scikit-learn/iris --split 'train[:10]' --revision main --table IrisSample
```

Choose a named Hugging Face configuration and its validation split:

```bash
iristool-hf stanfordnlp/sst2 --config default --split validation --table Sentiment
```

These create new tables. To replace an existing target, add `--replace`; **this deletes its previous data**. `main` follows the repository's branch; use a commit ID with `--revision` when you need a fixed revision.

**Python example** — reuse the `connection` dictionary from the quick start.
Pass pandas CSV options through `read_csv_kwargs`; here, `Id` is read as text instead of being inferred as an integer:

```python
from iristool import IRIStool
from iristool.integrations import import_kaggle

with IRIStool(**connection) as db:
    import_kaggle(
        db,
        "uciml/iris",
        file="Iris.csv",
        table="FlowersTextID",
        schema="SQLUser",
        read_csv_kwargs={"dtype": {"Id": "string"}},
    )
```

iristool uses the resulting pandas dtypes to infer SQL types. In Python, `replace=True` has the same destructive replacement behavior as `--replace`.

## Export a table

Save a table as CSV, Excel, or JSON

`export_table()` is part of the core. It reads the whole table into a pandas DataFrame and selects the writer from the output extension:

```python
with IRIStool(**connection) as db:
    db.export_table("KaggleIris", "iris.csv")
    db.export_table("KaggleIris", "iris.xlsx", sheet_name="Iris")
    db.export_table("KaggleIris", "iris.json", indent=2)
```

Use the `KaggleIris` table imported above, or replace its name with your table.
`table_schema="SQLUser"` is the default; pass another schema separately.
The method returns a `pathlib.Path`. Output directories must already exist.
CSV uses UTF-8, CSV/XLSX omit the pandas index, and JSON is an array of row
objects with ISO dates and JSON `null` for missing values.

CSV and JSON need no additional dependency. For XLSX, install Excel support:

```bash
python -m pip install 'iristool[excel]'
# Or in an activated standalone uv environment:
uv pip install 'iristool[excel]'
# Local development before release:
uv sync --all-extras
```

Combine extras with `'iristool[integrations,excel]'` to include both source SDKs
and Excel. The `integrations` extra alone still includes only source SDKs.

An existing output file causes an error. To replace it explicitly:

```python
with IRIStool(**connection) as db:
    db.export_table("KaggleIris", "iris.csv", overwrite=True, sep=";")
```

Extra keyword arguments go to pandas `to_csv`, `to_excel`, or `to_json`. The entire table must fit in memory; no row ordering is guaranteed. For a filtered or ordered export, use `db.fetch(...)` and the pandas writer directly.
An output failure can leave a partial file; `overwrite=True` replaces the previous file once writing starts. This does not change the source table.

## Examples

**Python examples**

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

Table policies, inferred SQL types, and transactions

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

**Available methods**

Most table helpers default to `table_schema="SQLUser"`. See the method docstrings for complete signatures and options.


| Method                                                                              | Purpose                                                       |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `df_to_table(df, table_name, ...)`                                                  | Create a table and import a DataFrame                         |
| `export_table(table_name, path, table_schema="SQLUser", overwrite=False, **kwargs)` | Export a table to CSV/XLSX/JSON; refuse overwrites by default |
| `fetch(sql, parameters=None)`                                                       | Return query results as a DataFrame                           |
| `insert_row(table_name, values)`                                                    | Insert one dictionary of values                               |
| `insert_many(table_name, rows)`                                                     | Insert dictionaries in a batch                                |
| `update(table_name, new_values, filters)`                                           | Update matching rows                                          |
| `update_many(table_name, updates)`                                                  | Apply a list of `(new_values, filters)` pairs                 |
| `create_table(table_name, columns, ...)`                                            | Create a table from SQL type declarations                     |
| `add_columns(table_name, new_columns)`                                              | Add columns to an existing table                              |
| `drop_table(table_name, ...)`                                                       | Drop a table, or a view with `view_or_table="view"`           |
| `table_exists(table_name)`                                                          | Check whether a table or view exists                          |
| `describe_table(table_name)`                                                        | Return column and index metadata                              |
| `create_index(index_name, table_name, column_name, ...)`                            | Create an index                                               |
| `index_exists(table_name, index_name)`                                              | Check index metadata                                          |
| `create_view(view_name, sql, ...)`                                                  | Create a SQL view                                             |
| `views_using_table(table_name)`                                                     | List dependent views                                          |
| `show_namespace_tables(...)`                                                        | List tables, with optional name/schema filters                |
| `show_namespace_schemas()`                                                          | List schemas containing base tables                           |
| `close()`                                                                           | Close the connection explicitly                               |




## Development and testing

The commands in this section test the local source checkout. To test the published package instead, use the isolated PyPI environment described in [installation](#installation) and the dataset import examples above.

Local setup, Docker, and test commands

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

## Troubleshooting

Common problems and solutions


| Symptom                                 | What to check                                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Integrations missing after pip install  | Install iristool 0.3.1 or newer with the desired source extra                                          |
| Connection refused                      | Check that IRIS is running and the SuperServer port is reachable; this Compose setup maps it to `9091` |
| Authentication failure                  | Check the account, password, namespace access, and password expiration                                 |
| Table already exists                    | Choose skip/replacement explicitly, or use row helpers to insert into it                               |
| Invalid identifier or colliding columns | Rename columns before importing; follow the naming rules above                                         |
| Constraint failure in a batch           | Correct the offending data; inserted rows roll back, but the created table remains                     |
| Timezone-aware datetime rejected        | Convert to the desired timezone, then remove timezone information                                      |




## Project layout

Repository files

```text
.
├── src/iristool/
│   ├── __init__.py         Public IRIStool import
│   ├── core.py             DataFrame and SQL helpers
│   └── integrations/       Optional Kaggle / Hugging Face downloads and CLI
├── tests/
│   ├── test_iristool.py    Unit tests
│   └── test_iris_integration.py  Opt-in live IRIS tests
├── .github/workflows/publish.yml  Tests, build, and tag-triggered PyPI publishing
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

## Credits and license

Created by **Pietro Di Leo**, based on the Python utilities from [iris_tool_and_data_manager](https://github.com/pietrodileo/iris_tool_and_data_manager).

Released under the **MIT License**. Copyright © 2025–2026 Pietro Di Leo.

See [LICENSE](LICENSE) for the full license text. A copy is included in both the Python wheel and source distribution.