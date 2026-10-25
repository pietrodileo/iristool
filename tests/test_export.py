import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from test_iristool import disconnected_tool


class ExportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.db, self.cursor = disconnected_tool()
        self.cursor.description = [('Name',), ('Score',)]
        self.cursor.fetchall.return_value = [('Città', 1.5), ('Ada', None)]

    def test_csv_preserves_columns_unicode_and_nulls(self):
        path = self.db.export_table('People', self.folder / 'people.csv')
        self.cursor.execute.assert_called_once_with('SELECT * FROM "SQLUser"."People"')
        frame = pd.read_csv(path)
        self.assertEqual(frame.columns.tolist(), ['Name', 'Score'])
        self.assertEqual(frame.loc[0, 'Name'], 'Città')
        self.assertTrue(pd.isna(frame.loc[1, 'Score']))
        self.db.conn.close.assert_not_called()

    def test_json_records_with_iso_dates(self):
        self.cursor.description = [('Day',), ('Score',)]
        self.cursor.fetchall.return_value = [(pd.Timestamp('2026-10-25'), None)]
        path = self.db.export_table('People', self.folder / 'people.json')
        data = json.loads(path.read_text())
        self.assertEqual(data, [{'Day': '2026-10-25T00:00:00.000', 'Score': None}])

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'requires iristool[excel]')
    def test_xlsx_roundtrip(self):
        path = self.db.export_table('People', self.folder / 'people.xlsx', sheet_name='People')
        frame = pd.read_excel(path, sheet_name='People')
        self.assertEqual(frame.columns.tolist(), ['Name', 'Score'])
        self.assertEqual(frame.loc[0, 'Name'], 'Città')
        self.assertTrue(pd.isna(frame.loc[1, 'Score']))

    def test_empty_table_keeps_csv_headers_and_json_is_empty_array(self):
        self.cursor.fetchall.return_value = []
        csv = self.db.export_table('People', self.folder / 'empty.csv')
        self.assertEqual(pd.read_csv(csv).columns.tolist(), ['Name', 'Score'])
        data = self.db.export_table('People', self.folder / 'empty.json')
        self.assertEqual(json.loads(data.read_text()), [])

    def test_existing_file_is_protected_and_replacement_is_explicit(self):
        path = self.folder / 'people.csv'
        path.write_text('keep me')
        with self.assertRaises(FileExistsError):
            self.db.export_table('People', path)
        self.assertEqual(path.read_text(), 'keep me')
        self.cursor.execute.assert_not_called()
        self.db.export_table('People', path, overwrite=True, sep=';')
        self.assertTrue(path.read_text().startswith('Name;Score'))

    def test_invalid_format_or_identifier_does_not_query_or_write(self):
        for name, filename in [('People', 'people.txt'), ('Bad;DROP', 'people.csv')]:
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.db.export_table(name, self.folder / filename)
        self.cursor.execute.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_missing_excel_dependency_gives_install_hint_before_query(self):
        with patch.dict('sys.modules', {'openpyxl': None}):
            with self.assertRaisesRegex(ImportError, r'iristool\[excel\]'):
                self.db.export_table('People', self.folder / 'people.xlsx')
        self.cursor.execute.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_query_failure_does_not_create_output(self):
        self.cursor.execute.side_effect = RuntimeError('SQL failed')
        with self.assertRaisesRegex(RuntimeError, 'SQL failed'):
            self.db.export_table('People', self.folder / 'people.csv')
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_fetch_without_result_metadata_still_returns_empty_frame(self):
        self.cursor.fetchall.return_value = []
        self.cursor.description = None
        self.assertTrue(self.db.fetch('SELECT 1 WHERE 1 = 0').empty)
