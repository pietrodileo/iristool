# Adding dataset sources to iristool

Keep each source inside `iristool.integrations`. Its job is to download data
and produce pandas DataFrames. **IRIStool remains responsible for recognizing
SQL types, creating tables, inserting rows, and handling database errors.**

Run the commands below from the `iristool` repository root. A separate project
or package is not required.

## Local development environment

For local development, testing, and running examples, use uv to create a virtual
environment (`.venv`) inside the `iristool` source folder. No separate `uv venv`
step is needed: run one of these commands to create the environment and install
the dependencies for the features you want to test:


| Command                       | What is installed in the project's `.venv`                                  |
| ----------------------------- | --------------------------------------------------------------------------- |
| `uv sync`                     | iristool, pandas, the IRIS driver, and their dependencies; no source SDKs   |
| `uv sync --extra kaggle`      | The base installation plus `kagglehub` and its dependencies                 |
| `uv sync --extra huggingface` | The base installation plus `datasets` and its dependencies                  |
| `uv sync --all-extras`        | The base installation plus every declared extra; currently both source SDKs |


These commands create or update `.venv` and install iristool in editable mode,
so source edits are available without reinstalling. Run tests and examples with
`uv run` to use this environment; manual activation is not required.
They do not download any
datasets, start IRIS, or import data. `uv sync` removes packages that are not
needed by the selected configuration: switching from `--all-extras` to
`--extra kaggle` removes packages needed only by Hugging Face support.

When running commands in this checkout, request the same extras, for example
`uv run --extra kaggle kaggle-iris --help` or
`uv run --all-extras python -m unittest discover -s tests -v -b`.
Plain `uv run` does not request the checkout's optional extras. Avoid mixing
pip installs into this uv-managed environment. Quote bracketed package names
in shells such as zsh.

Alternatively, install the source in editable mode with pip:

```bash
python -m pip install -e '.[integrations]'  # both sources
python -m pip install -e '.[kaggle]'        # Kaggle only
python -m pip install -e '.[huggingface]'   # Hugging Face only
```

Here `.` means the current source folder and `-e` makes source edits available
without reinstalling. These are developer commands; users install the published
package by name as shown in the README.

## Current structure

```text
src/iristool/
├── core.py                      IRIStool and the DataFrame-to-IRIS implementation
└── integrations/
    ├── __init__.py               Public aliases: import_kaggle, import_huggingface
    ├── _shared.py                Identifier validation and common write path
    ├── kaggle.py                 Download CSV/TSV files and read them with pandas
    ├── huggingface.py            Load a dataset split and convert it to pandas
    └── cli.py                    Command arguments and connection ownership
```

The flow for every source should stay simple:

```text
source SDK → pandas DataFrame → _import_frames → IRIStool.df_to_table → IRIS
```

The functions in `kaggle.py` and `huggingface.py` are both named
`import_dataset`. The package exposes distinct public names through aliases:

```python
# integrations/__init__.py
from .kaggle import import_dataset as import_kaggle
from .huggingface import import_dataset as import_huggingface
```

This is why `from . import import_kaggle, import_huggingface` works in `cli.py`.

## 1. Add one source adapter

Create `src/iristool/integrations/<source>.py`. Follow the existing adapters:

- Accept an **already open** `IRIStool` connection as the first argument.
- Accept a source identifier as `dataset`, with source-specific keyword options.
- Keep the common `table=None`, `schema="SQLUser"`, and `replace=False` options.
- Validate identifiers, target names, and selected files before downloading.
- Import the optional SDK inside the function, with an actionable install error.
- Convert the downloaded data into DataFrames and pass them to `_import_frames`.
- Return `{qualified_table: row_count}` and let failures reach the caller.
- Leave the caller's connection open, including when an import fails.

The following is a **template**, not an existing provider. Replace the SDK,
identifier rules, and download/conversion call with the real source's API:

```python
from ._shared import _import_frames, _name, _validate_target


def import_dataset(db, dataset, *, table=None, schema="SQLUser", replace=False):
    try:
        from example_sdk import download_frame
    except ImportError as exc:
        raise ImportError(
            'Install Example support with: pip install "iristool[example]"'
        ) from exc

    if not isinstance(dataset, str) or not dataset.strip():
        raise ValueError("Provide an Example dataset identifier.")
    # Add the provider's identifier/URL rules here before making requests.
    _validate_target(table, schema)
    name = table or _name("Example_" + dataset)
    frame = download_frame(dataset)  # Must return a pandas DataFrame.
    return _import_frames(db, [(dataset, frame, name)], schema, replace)
```

Each item passed to `_import_frames` is `(source_label, dataframe, table_name)`.
The label is used in progress output; the table name must already be validated
or normalized. The helper normalizes column names and rejects column names that
collide after normalization, ignoring case.

For multiple files or splits, determine all target names first and reject
duplicate names before writing any tables. The Kaggle adapter demonstrates this
and reads files one at a time. Imports across several tables are not atomic:
an error in a later table can leave earlier tables imported.

Preserve pandas dtypes and missing values. Avoid converting the whole frame to
strings or manually creating SQL columns. Nested objects and media need an
explicit policy: reject them with a helpful message, or offer a documented
conversion. The Hugging Face adapter currently rejects them. Each DataFrame
must fit in memory; do not promise streaming unless it is implemented and tested.

Use the provider's authentication and cache mechanisms. Document token setup,
private/gated access, and license acceptance where applicable. Never commit
credentials, print tokens, or bypass source access restrictions. For downloaded
files, validate paths and prevent selection outside the download directory.

## 2. Export the public function

Add an alias and update `__all__` in `integrations/__init__.py`:

```python
from .example import import_dataset as import_example

# Append "import_example" to the existing __all__ list.
```

The resulting Python interface should look like this:

```python
from iristool import IRIStool
from iristool.integrations import import_example

with IRIStool(host="localhost", port=9091, namespace="USER",
              username="_SYSTEM", password="SYS") as db:
    result = import_example(db, "dataset-id", table="ExampleData")
```

No changes to `core.py` are needed for a new download source. If a general
DataFrame-to-SQL issue is discovered, fix it in core with its own regression test.

## 3. Register the optional dependency and CLI

In `pyproject.toml`:

1. Add a source extra under `[project.optional-dependencies]`, with a tested
  SDK version range.
2. Include the same dependency in the existing `integrations` extra.
3. Add a `[project.scripts]` entry such as
  `example-iris = "iristool.integrations.cli:main_example"`.

Keep source SDKs out of the base `dependencies`. Importing `iristool` or
`iristool.integrations` must work without any source extras installed.

In `cli.py`, import the new public alias and add `main_example(default_port=1972)`.
Build an `argparse` parser using `dataset` and the common `--table`, `--schema`,
and `--replace` flags, then call `_run(parser, import_example, default_port)`.
Argument destinations must match the adapter's keyword names: `_run` forwards
`vars(args)` directly to the adapter.

Reuse `_connection` and `_run`: they read `IRIS_*` settings, own and close the
connection, and turn failures into a nonzero exit. Python adapters do not own
connections. Keep provider SDK imports lazy so CLI `--help` works without extras.
Replacement must remain opt-in: `--replace` deletes and recreates the table.

Refresh dependencies after editing the package metadata:

```bash
uv lock
uv sync --all-extras
```

## 4. Test the source boundary

Add `tests/test_<source>.py`. Follow `test_kaggle.py` or `test_huggingface.py`:
mock downloads, use real small DataFrames, and mock `db.df_to_table`. Cover:

- The expected source request and forwarded options.
- Integer, float, text, and missing values reaching `df_to_table` unchanged.
- Table/schema names, returned row counts, and explicit replacement behavior.
- Invalid identifiers, paths, nested data, and naming collisions before writes.
- Download/authentication failures propagating without writes; caller-owned
connections staying open.
- CLI argument forwarding and nonzero failure exits.

Extend `test_optional_integrations.py` to check the missing-SDK install message.
Source tests that require an SDK should skip cleanly when it is absent.

Run the unit suite with all current extras installed:

```bash
uv run --all-extras python -m unittest discover -s tests -v -b
```

Add an opt-in live test to `tests/test_dataset_integration.py` when the source
can provide a small, stable dataset. Give it a separate environment flag, use a
unique table name, check row counts and inferred SQL types, and clean up the
table in `finally`. Never make ordinary unit tests depend on network access,
credentials, or a running database.

For the existing providers, start the repository's Docker IRIS server and run:

```bash
docker compose up -d --build
# Wait until IRIS is ready. This repository maps its SQL port to 9091.
IRIS_PORT=9091 IRIS_INTEGRATION=1 KAGGLE_IRIS_INTEGRATION=1 HF_IRIS_INTEGRATION=1 \
  uv run --all-extras python -m unittest discover -s tests -v -b
```

Also verify a clean installation with **no extras**. An existing environment
with previously installed SDKs cannot prove that the base package stays light.
See the [release checklist](publish.md) for package build and install checks.

## 5. Document and ship

Update the README with the source's installation extra, authentication steps,
one-command example, Python example, options, supported formats, and limits.
Explain which datasets work without credentials and which require authorization.
Update the project layout when adding a module, commit the refreshed lockfile,
and follow [publishing instructions](publish.md) when preparing a release.

Start with one adapter and the existing helpers. A source registry or plugin
framework is unnecessary for adding another provider; introduce shared code
only when real adapters need the same behavior.