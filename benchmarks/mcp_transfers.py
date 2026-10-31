"""Compare existing DataFrame transfers with bounded-memory transfers on live IRIS.

Run: .venv/bin/python benchmarks/mcp_transfers.py --rows 100000 --repeat 3
Uses IRIS_* variables (development default port 9091). Creates unique temporary
SQLUser tables and removes them. Each measurement runs in a fresh process.
"""
import argparse
import contextlib
import csv
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter
import uuid

CASES = ('import_full', 'import_chunks', 'index_before', 'index_after', 'export_full', 'export_chunks',
         'export_subset_full', 'export_subset_chunks')
TYPES = {'Number': 'INT', 'Name': 'VARCHAR(255)', 'Text': 'VARCHAR(255)'}


def measure(case, source, rows):
    import pandas as pd
    from iristool import IRIStool

    table = 'IRISTool_Bench_' + uuid.uuid4().hex[:12]
    with contextlib.redirect_stdout(sys.stderr), IRIStool(
            host=os.getenv('IRIS_HOST', 'localhost'), port=int(os.getenv('IRIS_PORT', '9091')),
            namespace=os.getenv('IRIS_NAMESPACE', 'USER'), username=os.getenv('IRIS_USER', '_SYSTEM'),
            password=os.getenv('IRIS_PASSWORD', 'SYS')) as db:
        try:
            if case.startswith('export'):
                db.import_file(source, table, column_types=TYPES, chunk_size=10000)
            started = perf_counter()
            if case in ('import_full', 'index_before', 'index_after'):
                frame = pd.read_csv(source, dtype_backend='numpy_nullable')
                db.df_to_table(frame, table, column_types=TYPES, batch_size=1000,
                               indices=[{'column': 'Name'}] if case == 'index_before' else None)
                if case == 'index_after':
                    db.create_index(table + '_Name_index', table, 'Name')
            elif case == 'import_chunks':
                db.import_file(source, table, column_types=TYPES, chunk_size=10000, batch_size=1000)
            else:
                output = source.with_name(case + '.csv')
                if case.startswith('export_subset'):
                    db.export_query(f'SELECT "Number", "Text" FROM "SQLUser"."{table}" WHERE "Number" >= ?',
                                    output, parameters=[rows // 2], overwrite=True,
                                    chunk_size=None if case == 'export_subset_full' else 10000)
                elif case == 'export_full':
                    db.export_table(table, output, overwrite=True, chunk_size=None)
                else:
                    db.export_table(table, output, overwrite=True, chunk_size=10000)
            elapsed = perf_counter() - started
            # Capture RSS before correctness checks materialize exported data.
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_mib = rss / (1024**2 if sys.platform == 'darwin' else 1024)
            assert int(db.fetch(f'SELECT COUNT(*) AS N FROM SQLUser.{table}').iloc[0, 0]) == rows
            value = db.fetch(f'SELECT Name, Text FROM SQLUser.{table} WHERE Number = ?', [1])
            assert value.iloc[0, 0] == 'Città_1' and value.iloc[0, 1] == 'x' * 200
            if case.startswith('export'):
                with output.open(newline='', encoding='utf-8') as exported:
                    records = csv.DictReader(exported)
                    expected = rows - rows // 2 if case.startswith('export_subset') else rows
                    assert sum(1 for _ in records) == expected
                    if case.startswith('export_subset'):
                        assert records.fieldnames == ['Number', 'Text']
            if case.startswith('index'):
                assert db.index_exists(table, table + '_Name_index')
            result_rows = rows - rows // 2 if case.startswith('export_subset') else rows
            return {'case': case, 'seconds': round(elapsed, 4),
                    'rows_per_second': round(result_rows / elapsed), 'peak_rss_mib': round(rss_mib, 1)}
        finally:
            db.drop_table(table)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, default=100000)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--cases', nargs='+', choices=CASES, default=CASES)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    if args.rows < 1 or args.repeat < 1:
        parser.error('rows and repeat must be positive')
    if args.case:
        print(json.dumps(measure(args.case, args.source, args.rows)))
        return
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / 'source.csv'
        with source.open('w', encoding='utf-8', newline='') as output:
            writer = csv.writer(output)
            writer.writerow(TYPES)
            for number in range(args.rows):
                writer.writerow((number, 'Città_' + str(number % 10000), 'x' * 200))
        results = []
        cases = tuple(args.cases)
        # Rotate order across repeats to reduce systematic warm-cache advantage.
        for repeat in range(args.repeat):
            for case in cases[repeat % len(cases):] + cases[:repeat % len(cases)]:
                result = subprocess.run([sys.executable, __file__, '--case', case,
                                         '--source', str(source), '--rows', str(args.rows)],
                                        check=True, capture_output=True, text=True)
                measurement = json.loads(result.stdout)
                results.append(measurement)
                print(json.dumps(measurement), flush=True)
        report = {'rows': args.rows, 'repeat': args.repeat, 'python': sys.version.split()[0],
                  'platform': sys.platform, 'measurements': results,
                  'medians': {case: {key: statistics.median(r[key] for r in results if r['case'] == case)
                                    for key in ('seconds', 'rows_per_second', 'peak_rss_mib')}
                              for case in cases}}
        if args.output:
            args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report['medians'], indent=2))


if __name__ == '__main__':
    main()
