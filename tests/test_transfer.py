import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd

from iristool.transfer import import_file, export_file
from test_iristool import disconnected_tool


class TransferTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.db, self.cursor = disconnected_tool()

    def test_append_preserves_table_and_indexes_in_full_and_chunked_imports(self):
        source = self.folder / 'users.csv'
        source.write_text('Name\nAda\nGrace\n')
        for chunk_size in (None, 1):
            with self.subTest(chunk_size=chunk_size):
                db, cursor = disconnected_tool()
                db.table_exists = Mock(return_value=True)
                db.create_table = Mock()
                db.drop_table = Mock()
                count = db.import_file(source, 'users', append=True, chunk_size=chunk_size,
                                       batch_size=1)
                self.assertEqual(count, 2)
                self.assertEqual([c.args[1] for c in cursor.executemany.call_args_list],
                                 [[('Ada',)], [('Grace',)]])
                db.create_table.assert_not_called()
                db.drop_table.assert_not_called()
                cursor.execute.assert_not_called()  # No DDL or index changes.
                db.conn.commit.assert_called_once()

    def test_append_rejects_replace_or_missing_table_before_insertion(self):
        self.db.table_exists = Mock(return_value=False)
        for options, message in (({'append': True, 'replace': True}, 'mutually exclusive'),
                                 ({'append': True}, 'existing table')):
            with self.assertRaisesRegex(ValueError, message):
                self.db.import_file(self.folder / 'missing.csv', 'users', **options)
        self.cursor.executemany.assert_not_called()
        self.db.conn.commit.assert_not_called()

    def test_append_failure_rolls_back_all_batches_without_ddl(self):
        source = self.folder / 'users.csv'
        source.write_text('Name\nAda\nAda\n')
        self.db.table_exists = Mock(return_value=True)
        self.cursor.rowcount = 1
        self.cursor.executemany.side_effect = [None, RuntimeError('unique constraint')]
        with self.assertRaisesRegex(RuntimeError, 'unique constraint'):
            self.db.import_file(source, 'users', append=True, chunk_size=1,
                                column_types={'Name': 'VARCHAR(255)'}, batch_size=1)
        self.db.conn.commit.assert_not_called()
        self.db.conn.rollback.assert_called_once()
        self.cursor.execute.assert_not_called()

    def test_csv_chunks_preserve_nullable_large_integer_and_unicode(self):
        source = self.folder / 'input.csv'
        source.write_text('Number,Name\n9007199254740993,Città\n,Grace\n3,Ada\n')
        count = self.db.import_file(source, 'People', chunk_size=2, batch_size=1,
                            column_types={'Number': 'BIGINT', 'Name': 'VARCHAR(255)'})
        self.assertEqual(count, 3)
        calls = self.cursor.executemany.call_args_list
        self.assertEqual([c.args[1][0] for c in calls],
                         [(9007199254740993, 'Città'), (None, 'Grace'), (3, 'Ada')])
        self.db.conn.rollback.assert_not_called()

    def test_streaming_requires_explicit_schema_before_ddl(self):
        for filename in ('input.csv', 'input.xlsx', 'input.json'):
            with self.assertRaisesRegex(ValueError, 'Streaming imports require'):
                import_file(self.db, self.folder / filename, 'People', chunk_size=10)
        self.cursor.execute.assert_not_called()

    def test_later_chunk_failure_rolls_back_without_committing_earlier_rows(self):
        source = self.folder / 'input.csv'
        source.write_text('Number\n1\n2\n')
        commits_at_insert = []
        def insert(sql, rows):
            commits_at_insert.append(self.db.conn.commit.call_count)
            self.cursor.rowcount = len(rows)
            if rows == [(2,)]:
                raise RuntimeError('bad row')
        self.cursor.executemany.side_effect = insert
        with self.assertRaisesRegex(RuntimeError, 'bad row'):
            import_file(self.db, source, 'People', chunk_size=1,
                        column_types={'Number': 'INT'})
        self.assertEqual(commits_at_insert, [2, 2])  # DDL and empty df_to_table, before any row.
        self.assertEqual(self.db.conn.commit.call_count, 2)
        self.db.conn.rollback.assert_called_once()

    def test_json_and_jsonl_preserve_nullable_integer_precision(self):
        for suffix in ('.json', '.jsonl'):
            source = self.folder / ('input' + suffix)
            rows = [{'N': 9007199254740993}, {'N': None}, {'N': 1}]
            source.write_text(json.dumps(rows) if suffix == '.json' else
                              '\n'.join(json.dumps(row) for row in rows))
            self.cursor.executemany.reset_mock()
            import_file(self.db, source, 'Data')
            self.assertEqual(self.cursor.executemany.call_args.args[1],
                             [(9007199254740993,), (None,), (1,)])
        self.cursor.executemany.reset_mock()
        import_file(self.db, source, 'Data', chunk_size=2, column_types={'N': 'BIGINT'})
        self.assertEqual(self.cursor.executemany.call_args_list[0].args[1],
                         [(9007199254740993,), (None,)])

    def test_csv_tsv_and_empty_csv(self):
        for suffix, content, count in [('.csv', 'N\n1\n', 1), ('.tsv', 'N\tName\n1\tAda\n', 1),
                                        ('.csv', 'N\n', 0)]:
            source = self.folder / ('data' + suffix)
            source.write_text(content)
            self.assertEqual(import_file(self.db, source, 'Data'), count)

    def test_mixed_json_numbers_infer_double_without_silent_large_integer_rounding(self):
        source = self.folder / 'input.json'
        source.write_text('[{"N": 1}, {"N": 1.5}, {"N": null}]')
        import_file(self.db, source, 'Data')
        self.assertIn('DOUBLE', self.cursor.execute.call_args_list[0].args[0])
        source.write_text('[{"N": 9007199254740993}, {"N": 1.5}]')
        with self.assertRaisesRegex(ValueError, 'preserve precision'):
            import_file(self.db, source, 'Data')

    def test_streaming_empty_csv_creates_empty_table(self):
        source = self.folder / 'empty.csv'
        source.write_text('N\n')
        self.assertEqual(import_file(self.db, source, 'Data', chunk_size=2,
                                     column_types={'N': 'INT'}), 0)
        self.cursor.executemany.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'requires excel extra')
    def test_xlsx_sheet_selection(self):
        source = self.folder / 'data.xlsx'
        pd.DataFrame({'N': [1, 2]}).to_excel(source, sheet_name='Data', index=False)
        self.assertEqual(import_file(self.db, source, 'Data', sheet_name='Data'), 2)

    def test_streaming_export_formats_and_precision(self):
        for suffix in ('.csv', '.json', '.jsonl'):
            self.cursor.description = [('N',), ('Name',)]
            self.cursor.fetchmany.side_effect = [[(9007199254740993, 'Città'), (None, 'Ada')], [(1, 'Grace')], []]
            path = self.folder / ('out' + suffix)
            result = export_file(self.db, 'People', path, chunk_size=2)
            self.assertEqual(result['rows'], 3)
            self.assertIn('9007199254740993', path.read_text())
            if suffix == '.json':
                self.assertEqual(json.loads(path.read_text())[0]['N'], 9007199254740993)
            elif suffix == '.jsonl':
                self.assertEqual(len(path.read_text().splitlines()), 3)
            else:
                self.assertEqual(path.read_text().count('N,Name'), 1)
            self.cursor.fetchall.assert_not_called()

    def test_empty_exports(self):
        self.cursor.description = [('N',)]
        for suffix, expected in (('.csv', 'N\n'), ('.json', '[]'), ('.jsonl', '')):
            self.cursor.fetchmany.side_effect = [[]]
            path = self.folder / ('empty' + suffix)
            export_file(self.db, 'Data', path)
            self.assertEqual(path.read_text(), expected)

    def test_failed_export_preserves_previous_file_and_removes_temporary(self):
        self.cursor.description = [('N',)]
        self.cursor.fetchmany.side_effect = [[(1,)], RuntimeError('lost connection')]
        path = self.folder / 'out.csv'
        path.write_text('previous')
        with self.assertRaisesRegex(RuntimeError, 'lost connection'):
            export_file(self.db, 'People', path, overwrite=True)
        self.assertEqual(path.read_text(), 'previous')
        self.assertEqual(list(self.folder.iterdir()), [path])

    def test_export_no_clobber_and_bad_chunk_size(self):
        path = self.folder / 'out.csv'
        path.write_text('previous')
        with self.assertRaises(FileExistsError):
            export_file(self.db, 'People', path)
        for size in (0, -1, True):
            with self.assertRaises(ValueError):
                export_file(self.db, 'People', path, chunk_size=size)
        self.cursor.execute.assert_not_called()
