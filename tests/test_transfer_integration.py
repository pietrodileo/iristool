"""Opt-in IRIS checks for MCP transfers: IRIS_INTEGRATION=1."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

from iristool import IRIStool


@unittest.skipUnless(os.getenv('IRIS_INTEGRATION') == '1', 'requires a running IRIS server')
class TransferIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = IRIStool(host=os.getenv('IRIS_HOST', 'localhost'),
                           port=int(os.getenv('IRIS_PORT', '9091')),
                           namespace=os.getenv('IRIS_NAMESPACE', 'USER'),
                           username=os.getenv('IRIS_USER', '_SYSTEM'),
                           password=os.getenv('IRIS_PASSWORD', 'SYS'))
        self.table = 'IRISTool_Transfer_' + uuid.uuid4().hex[:12]
        self.addCleanup(self.cleanup)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def cleanup(self):
        try:
            self.db.drop_table(self.table)
        finally:
            self.db.close()

    def test_streaming_round_trip_preserves_large_int_null_and_unicode(self):
        source = self.root / 'source.csv'
        source.write_text('Number,Name\n9007199254740993,Città\n,Grace\n3,Ada\n')
        self.assertEqual(self.db.import_file(source, self.table, chunk_size=2, batch_size=1,
                                     column_types={'Number': 'BIGINT', 'Name': 'VARCHAR(255)'}), 3)
        for suffix in ('.csv', '.json', '.jsonl'):
            output = self.root / ('out' + suffix)
            result = self.db.export_table(self.table, output, chunk_size=2)
            self.assertEqual(result, output)
            self.assertIn('9007199254740993', output.read_text())
            if suffix == '.json':
                rows = json.loads(output.read_text())
                self.assertIn({'Number': 9007199254740993, 'Name': 'Città'}, rows)
                self.assertIn({'Number': None, 'Name': 'Grace'}, rows)

    def test_query_and_structured_subsets_match_on_live_iris(self):
        import pandas as pd
        payload = "x'; DROP TABLE People; --"
        self.db.df_to_table(pd.DataFrame({'Number': pd.array([9007199254740993, None, 3, 4], dtype='Int64'),
                                         'Name': ['Città', 'Grace', payload, 'Ada']}), self.table)
        query = f'SELECT "Number", "Name" FROM "SQLUser"."{self.table}" WHERE "Number" >= ? ORDER BY "Number" DESC'
        raw = self.db.export_query(query, self.root / 'query.json', parameters=[3], chunk_size=1)
        structured = self.db.export_table(self.table, self.root / 'subset.json', columns=['Number', 'Name'],
            filters=[{'column': 'Number', 'op': '>=', 'value': 3}],
            order_by=[{'column': 'Number', 'direction': 'DESC'}], limit=2, chunk_size=1)
        self.assertEqual(json.loads(structured.read_text()), json.loads(raw.read_text())[:2])
        selected = self.db.export_table(self.table, self.root / 'bound.json', columns=['Number'],
            filters=[{'column': 'Name', 'op': 'IN', 'value': [payload]}], chunk_size=1)
        self.assertEqual(json.loads(selected.read_text()), [{'Number': 3}])
        nulls = self.db.export_table(self.table, self.root / 'nulls.json', columns=['Name'],
            filters=[{'column': 'Number', 'op': 'IS NULL'}])
        self.assertEqual(json.loads(nulls.read_text()), [{'Name': 'Grace'}])
        empty = self.db.export_query(query, self.root / 'empty.csv', parameters=[9007199254740994], chunk_size=1)
        self.assertEqual(pd.read_csv(empty).columns.tolist(), ['Number', 'Name'])
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            self.db.export_table(self.table, self.root / 'bad.csv', columns=['Missing'])
        self.assertFalse((self.root / 'bad.csv').exists())

    def test_later_batch_failure_leaves_zero_inserted_rows(self):
        source = self.root / 'source.csv'
        source.write_text('Number\n1\n2\nnot-an-integer\n')
        with self.assertRaises(Exception):
            self.db.import_file(source, self.table, chunk_size=1, batch_size=1,
                        column_types={'Number': 'INT'})
        self.assertEqual(int(self.db.fetch(f'SELECT COUNT(*) AS N FROM SQLUser.{self.table}').iloc[0, 0]), 0)

    @unittest.skipUnless(importlib.util.find_spec('fastmcp'), 'requires iristool[mcp]')
    def test_stdio_mcp_import_metadata_index_and_export(self):
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport
        # Password stays in the environment; this file never contains it.
        config = self.root / '.iristool.toml'
        config.write_text('[instance.dev]\nhost = "' + self.db.host + '"\nport = ' + str(self.db.port) +
                          '\nnamespace = "' + self.db.namespace + '"\nusername = "' + self.db.username +
                          '"\npassword_env = "IRISTOOL_MCP_LIVE_PASSWORD"\n')
        (self.root / 'source.json').write_text('[{"Number": 9007199254740993}, {"Number": null}]')
        async def check():
            transport = StdioTransport(command=sys.executable,
                                       args=['-m', 'iristool.mcp_server', '--workspace', str(self.root)],
                                       env={'IRISTOOL_MCP_LIVE_PASSWORD': self.db.password},
                                       log_file=self.root / 'stdio.log')
            async with Client(transport) as client:
                result = (await client.call_tool('iris_import_file', {
                    'path': 'source.json', 'table': self.table})).data
                self.assertEqual(result['rows'], 2)
                await client.call_tool('iris_create_index', {
                    'table': self.table, 'column': 'Number', 'index': self.table + '_idx'})
                metadata = (await client.call_tool('iris_describe_table', {'table': self.table})).data
                self.assertIn('metadata', metadata)
                await client.call_tool('iris_export_table', {'table': self.table, 'path': 'out.json', 'chunk_size': 1})
                self.assertIn({'Number': 9007199254740993}, json.loads((self.root / 'out.json').read_text()))
                subset = (await client.call_tool('iris_export_table', {
                    'table': self.table, 'path': 'subset.json', 'chunk_size': 1,
                    'columns': ['Number'], 'filters': [{'column': 'Number', 'op': 'IS NOT NULL'}],
                    'order_by': [{'column': 'Number', 'direction': 'DESC'}], 'limit': 1})).data
                self.assertEqual(subset['rows'], 1)
                self.assertEqual(json.loads((self.root / 'subset.json').read_text()), [{'Number': 9007199254740993}])
        asyncio.run(check())
