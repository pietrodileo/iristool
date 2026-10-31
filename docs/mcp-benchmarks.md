# Core and MCP transfer benchmark

Measured on 2026-10-31 against local development IRIS. These are workload-specific
results, not throughput guarantees.

## Results

100,000 rows, three runs per case, median values:

| Operation | Existing path | New path | Existing peak RSS | New peak RSS |
| --- | ---: | ---: | ---: | ---: |
| CSV import | 0.8117 s | 0.7720 s | 168.8 MiB | 118.9 MiB |
| CSV export | 0.3500 s | 0.3445 s | 261.8 MiB | 154.2 MiB |
| Import with index before / after rows | 0.9015 s | 0.8861 s | 167.7 MiB | 166.3 MiB |

The strongest result is lower peak memory: approximately **30% for import** and
**41% for export**. The small timing differences do not support a general speed
claim. Index timing varied across runs, so the existing `df_to_table(indices=...)`
default was left unchanged. MCP callers can explicitly create secondary indexes
after loading.

## Core API confirmation

After sharing the implementation with core, the same 100,000-row, three-run
comparison through `db.import_file()` and `db.export_table()` measured:

| Operation | Whole-frame time | Streaming time | Whole-frame RSS | Streaming RSS |
| --- | ---: | ---: | ---: | ---: |
| CSV import | 0.7277 s | 0.6860 s | 167.9 MiB | 118.9 MiB |
| CSV export | 0.3492 s | 0.3444 s | 263.2 MiB | 154.6 MiB |

That confirms approximately 29% lower import memory and 41% lower export memory
through the core API. Timing remains workload-specific. The short live test
suite overlapped the start of this run; these timings are not isolated-load
measurements. Raw runs: [core-transfers-results.json](../benchmarks/core-transfers-results.json).
Core exports now stream by default. `chunk_size=None` retains the whole-frame
comparison path; custom pandas writer options and XLSX also use a whole frame.
Imports require explicit types to stream without guessing a schema from a sample.

## Filtered query export

Using `db.export_query()` on a 200,000-row source table, select `Number` and
`Text` where `Number >= 100000`. Both paths export the same 100,000 rows and
two columns with bound parameters. Three fresh-process runs per case, median:

| Path | Time | Peak RSS |
| --- | ---: | ---: |
| Whole selected result (`chunk_size=None`) | 0.3495 s | 251.2 MiB |
| Streaming selected result (`chunk_size=10000`) | 0.3455 s | 152.6 MiB |

Streaming reduced peak process memory by approximately 39%; timings are similar.
Source preparation uses streaming import, is excluded from elapsed export time,
and remains part of peak RSS. This comparison ran after the test suite finished.
Output row counts and selected column names are checked. Environment and input
shape match the core API confirmation above. Raw runs:
[subset-transfers-results.json](../benchmarks/subset-transfers-results.json).

```bash
.venv/bin/python benchmarks/mcp_transfers.py --rows 200000 --repeat 3 \
  --cases export_subset_full export_subset_chunks \
  --output benchmarks/subset-transfers-results.json
```

## Method

- macOS 27.0.1 ARM64, Python 3.12.13, pandas 3.1.0, NumPy 2.5.4,
  intersystems-irispython 5.4.1. MCP uses FastMCP 2.14.7.
- Local Docker IRIS for ARM64, IRIS Community 2026.2 Build 221U. Base image:
  `intersystems/iris-community:latest-cd`, resolved at test time to
  `sha256:cd2ebcab02d1ef80ec155def4418399f353d867162688c36a3705760e750bdaa`.
- Generated CSV: integer `Number`, repeating Unicode `Name` (10,000 distinct
  values), and 200-character `Text`; complete explicit SQL types in every case.
- Existing import: whole-file pandas read followed by `df_to_table`.
  New import: shared `import_file` / `db.import_file()`, 10,000-row chunks. Both use nullable pandas dtypes
  and 1,000-row `executemany` batches.
- Whole-frame export: original `export_table`, now selected with
  `chunk_size=None`. Streaming export: shared `export_file` / default
  `db.export_table()`, 10,000-row cursor chunks with atomic output publication.
- Index comparison: the existing DataFrame path with one ordinary `Name` index
  before insertion versus the same import followed by `create_index`.
- Each measurement uses a fresh Python subprocess and a uniquely named table.
  Connection setup and export-source preparation are excluded from elapsed time.
  Read/parse time is included in imports; writing is included in exports.
- Peak RSS is the process high-water mark, including Python/pandas startup and,
  for exports, source-table setup. It is not incremental allocation or IRIS server
  memory. Table count, selected values, output row counts, and index existence
  are checked after timing. Temporary tables are removed.
- Case order rotates across repetitions. The database remains warm; network
  latency, remote IRIS, concurrent users, larger files, different datatypes,
  XLSX, JSON, and provider downloads were not performance-benchmarked.

Raw runs are in [`benchmarks/mcp-transfers-results.json`](../benchmarks/mcp-transfers-results.json).

Correctness coverage is separate: unit and live IRIS tests cover streaming
rollback, nullable integers larger than 2^53, Unicode, empty outputs, atomic
export failure handling, stdio tool execution, routing, and read-only rejection.

## Reproduce

Start the repository's development IRIS server and install the local package:

```bash
docker compose up -d --build
uv sync --locked --all-extras
uv run --locked --all-extras python benchmarks/mcp_transfers.py \
  --rows 100000 --repeat 3 --output /tmp/iristool-benchmark.json
```

The script uses `IRIS_HOST`, `IRIS_PORT`, `IRIS_NAMESPACE`, `IRIS_USER`, and
`IRIS_PASSWORD`, defaulting to this repository's development server. Run it only
against an instance where creating and removing temporary SQLUser tables is
appropriate. Its `resource` RSS measurement supports macOS/Linux.

## Distribution size

The initial built wheel was approximately 40 KB, without dependencies. A fresh
Python 3.12 environment installed from that wheel with `mcp,excel` occupied
approximately 186 MiB on this Mac, excluding the separately managed Python
interpreter. HF/Kaggle extras were absent. This is installed disk usage, not a
measurement of network download size. uv/uvx manages dependencies separately;
no standalone runtime bundle is produced.
