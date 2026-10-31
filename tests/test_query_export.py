"""Streaming query exports and the SQL boundary used by MCP selection."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from iristool.transfer import table_query
from test_iristool import disconnected_tool


class QueryExportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db, self.cursor = disconnected_tool()
        self.cursor.description = [('Number',), ('Name',)]

    def test_query_binds_parameters_and_streams_exact_values(self):
        sql = 'SELECT Number, Name FROM SQLUser.People WHERE Name <> ?'
        value = "x'; DROP TABLE People; --"
        self.cursor.fetchmany.side_effect = [[(9007199254740993, 'Città')], [(None, 'Ada')], []]
        path = self.db.export_query(sql, self.root / 'people.json', parameters=[value], chunk_size=1)
        self.cursor.execute.assert_called_once_with(sql, [value])
        self.cursor.fetchall.assert_not_called()
        self.assertEqual(json.loads(path.read_text()),
                         [{'Number': 9007199254740993, 'Name': 'Città'}, {'Number': None, 'Name': 'Ada'}])
        self.db.conn.commit.assert_not_called()
        self.db.conn.close.assert_not_called()

    def test_query_full_frame_options_bind_parameters(self):
        self.cursor.fetchall.return_value = [(1, 'Ada')]
        path = self.db.export_query('SELECT Number, Name FROM SQLUser.People WHERE Number > ?',
                                    self.root / 'split.json', parameters=[0], orient='split')
        self.cursor.execute.assert_called_once_with('SELECT Number, Name FROM SQLUser.People WHERE Number > ?', [0])
        self.cursor.fetchmany.assert_not_called()
        self.assertEqual(json.loads(path.read_text())['data'], [[1, 'Ada']])

    def test_query_failure_is_atomic(self):
        path = self.root / 'out.csv'
        path.write_text('previous')
        self.cursor.fetchmany.side_effect = [[(1, 'Ada')], RuntimeError('lost connection')]
        with self.assertRaisesRegex(RuntimeError, 'lost connection'):
            self.db.export_query('SELECT Number, Name FROM SQLUser.People', path, overwrite=True)
        self.assertEqual(path.read_text(), 'previous')
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_query_empty_and_non_tabular_results(self):
        self.cursor.fetchmany.return_value = []
        path = self.db.export_query('SELECT Number, Name FROM SQLUser.People WHERE 1=0', self.root / 'empty.csv')
        self.assertEqual(pd.read_csv(path).columns.tolist(), ['Number', 'Name'])
        self.cursor.description = None
        with self.assertRaisesRegex(ValueError, 'tabular'):
            self.db.export_query('statement without result', self.root / 'no.csv')
        self.assertFalse((self.root / 'no.csv').exists())

    def test_structured_selection_generates_only_identifiers_and_placeholders(self):
        payload = "Ada' OR 1=1 --"
        sql, parameters = table_query(self.db, 'People', columns=['Name'],
            filters=[{'column': 'Number', 'op': '>=', 'value': 2},
                     {'column': 'Name', 'op': 'in', 'value': [payload, 'Grace']},
                     {'column': 'Number', 'op': 'IS NOT NULL'}],
            order_by=[{'column': 'Number', 'direction': 'desc'}], limit=3)
        self.assertEqual(sql, 'SELECT TOP 3 "Name" FROM "SQLUser"."People" WHERE "Number" >= ? '
                         'AND "Name" IN (?, ?) AND "Number" IS NOT NULL ORDER BY "Number" DESC')
        self.assertEqual(parameters, [2, payload, 'Grace'])
        self.assertNotIn(payload, sql)
        self.cursor.execute.assert_called_once_with('SELECT * FROM "SQLUser"."People" WHERE 1 = 0')
        self.cursor.fetchall.assert_not_called()

    def test_malformed_selection_fails_before_query_or_output(self):
        bad = [
            {'columns': []}, {'columns': ['Name', 'name']}, {'columns': ['Name; DROP TABLE People']},
            {'columns': 'Name'}, {'filters': 'Number > 1'},
            {'filters': [{'column': 'Name', 'op': '= ? OR 1=1', 'value': 'x'}]},
            {'filters': [{'column': 'Name', 'op': '=', 'value': {'sql': 'NOW()'}}]},
            {'filters': [{'column': 'Name', 'op': '=', 'value': None}]},
            {'filters': [{'column': 'Number', 'op': '=', 'value': float('nan')}]},
            {'filters': [{'column': 'Number', 'op': '=', 'value': float('inf')}]},
            {'filters': [{'column': 'Name', 'op': 'IN', 'value': []}]},
            {'filters': [{'column': 'Name', 'op': 'IN', 'value': ['x', None]}]},
            {'filters': [{'column': 'Name', 'op': 'IS NULL', 'value': None}]},
            {'filters': [{'column': 'Name', 'op': 'IS NULL', 'sql': 'x'}]},
            {'order_by': [{'column': 'Name', 'direction': 'ASC; DROP TABLE People'}]},
            {'order_by': [{'column': 'LOWER(Name)'}]}, {'order_by': ['Name']},
            *({'limit': limit} for limit in (0, -1, True, '1', 1.5)),
        ]
        for options in bad:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.db.export_table('People', self.root / 'bad.csv', **options)
        self.cursor.execute.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unknown_columns_fail_before_output(self):
        for options in ({'columns': ['Missing']},
                        {'filters': [{'column': 'Missing', 'op': 'IS NULL'}]},
                        {'order_by': [{'column': 'Missing'}]}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'Unknown'):
                self.db.export_table('People', self.root / 'unknown.csv', **options)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_all_comparison_operators_and_null(self):
        for op in ('=', '!=', '<>', '<', '<=', '>', '>='):
            sql, parameters = table_query(self.db, 'People', filters=[{'column': 'Number', 'op': op, 'value': 4}])
            self.assertTrue(sql.endswith('"Number" ' + op + ' ?'))
            self.assertEqual(parameters, [4])
        sql, parameters = table_query(self.db, 'People', filters=[{'column': 'Number', 'op': 'IS NULL'}])
        self.assertTrue(sql.endswith('"Number" IS NULL'))
        self.assertEqual(parameters, [])

    def test_table_and_query_share_writer(self):
        with patch('iristool.transfer.export_query', return_value={'rows': 0}) as writer:
            self.db.export_table('People', self.root / 'all.csv')
            self.assertEqual(writer.call_args.args[1], 'SELECT * FROM "SQLUser"."People"')
            self.db.export_query('SELECT 1 AS N', self.root / 'one.csv')
            self.assertEqual(writer.call_args.args[1], 'SELECT 1 AS N')
