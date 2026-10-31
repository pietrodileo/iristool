"""Two-container fleet checks: IRIS_FLEET_INTEGRATION=1 (see docs/mcp.md)."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
import uuid

from iristool import IRIStool


@unittest.skipUnless(os.getenv('IRIS_FLEET_INTEGRATION') == '1'
                     and importlib.util.find_spec('fastmcp'),
                     'requires the fleet Compose stack and iristool[mcp]')
class FleetIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.admins = {}
        self.users = {}
        self.table = 'Fleet_' + uuid.uuid4().hex[:12]
        self.created = self.table + '_New'
        self.password = secrets.token_hex(16)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup)
        for name, port, marker in (('writable', 9191, 'writer'), ('readonly', 9291, 'reader')):
            db = self.admins[name] = IRIStool(host='localhost', port=port, namespace='USER',
                username='_SYSTEM', password=os.getenv('IRIS_FLEET_ADMIN_PASSWORD', 'SYS'))
            db.create_table(self.table, {'Number': 'INT', 'Marker': 'VARCHAR(30)'})
            db.insert_row(self.table, {'Number': 1, 'Marker': marker})
            user = 'FleetUser_' + uuid.uuid4().hex[:12]
            self.sql(db, f'CREATE USER {user} IDENTIFIED BY "{self.password}"')
            self.users[name] = user
            self.sql(db, f'GRANT SELECT ON SQLUser.{self.table} TO {user}')
            if name == 'writable':
                self.sql(db, f'GRANT INSERT, UPDATE, DELETE ON SQLUser.{self.table} TO {user}')
                self.sql(db, f'GRANT %CREATE_TABLE, %ALTER_TABLE TO {user}')
        self.write_config(read_only=True)
        (self.root / 'source.csv').write_text('Number,Marker\n2,imported\n')

    @staticmethod
    def sql(db, statement):
        with db.conn.cursor() as cursor:
            cursor.execute(statement)
        db.conn.commit()

    def write_config(self, *, read_only):
        text = 'default_server = "writable"\n'
        for name, db in self.admins.items():
            text += (f'[instance.{name}]\nhost="localhost"\nport={db.port}\n'
                     f'namespace="USER"\nusername="{self.users[name]}"\n'
                     'password_env="IRISTOOL_FLEET_PASSWORD"\n'
                     f'read_only={str(name == "readonly" and read_only).lower()}\n')
        # Placeholder permits testing the write guard without contacting Kaggle.
        text += '[providers.kaggle]\ntoken="unused-fleet-test-token"\n'
        (self.root / '.iristool.toml').write_text(text)

    def cleanup(self):
        for name, db in self.admins.items():
            try:
                for table in (self.created, self.table):
                    if db.table_exists(table):
                        db.drop_table(table)
                if name in self.users:
                    self.sql(db, f'DROP USER {self.users[name]}')
            finally:
                db.close()

    def client(self):
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport
        return Client(StdioTransport(command=sys.executable,
            args=['-m', 'iristool.mcp_server'],
            env={'IRISTOOL_FLEET_PASSWORD': self.password},
            log_file=self.root / 'stdio.log'), roots=[self.root.as_uri()])

    def test_stdio_fleet_routes_reads_and_enforces_read_only(self):
        async def check():
            async with self.client() as client:
                servers = (await client.call_tool('iris_servers', {})).data
                self.assertEqual(servers['default_server'], 'writable')
                self.assertEqual({s['server']: s['read_only'] for s in servers['servers']},
                                 {'writable': False, 'readonly': True})
                self.assertNotIn(self.password, json.dumps(servers))
                async def read(name):
                    tables = (await client.call_tool('iris_tables', {'server': name})).data
                    self.assertIn(self.table, json.dumps(tables))
                    description = (await client.call_tool('iris_describe_table', {
                        'server': name, 'table': self.table})).data
                    self.assertTrue(description['metadata']['columns'])
                    result = (await client.call_tool('iris_export_table', {
                        'server': name, 'table': self.table, 'path': name + '.json',
                        'columns': ['Number', 'Marker'], 'limit': 1, 'chunk_size': 1})).data
                    self.assertEqual(result['server'], name)
                    self.assertEqual(result['rows'], 1)
                await asyncio.gather(read('writable'), read('readonly'))
                self.assertEqual(json.loads((self.root / 'writable.json').read_text()),
                                 [{'Number': 1, 'Marker': 'writer'}])
                self.assertEqual(json.loads((self.root / 'readonly.json').read_text()),
                                 [{'Number': 1, 'Marker': 'reader'}])
                for tool, args in (
                    ('iris_create_table', {'table': self.created, 'columns': {'Number': 'INT'}}),
                    ('iris_create_index', {'table': self.table, 'column': 'Number', 'index': 'Blocked'}),
                    ('iris_import_file', {'table': self.created, 'path': 'source.csv'}),
                    ('iris_import_huggingface', {'dataset': 'owner/data'}),
                    ('iris_import_kaggle', {'dataset': 'owner/data'}),
                ):
                    with self.subTest(tool=tool), self.assertRaisesRegex(Exception, 'read-only'):
                        await client.call_tool(tool, {'server': 'readonly', **args})
                # No server argument must route the import to the default writable instance.
                imported = (await client.call_tool('iris_import_file', {
                    'table': self.created, 'path': 'source.csv'})).data
                self.assertEqual(imported['server'], 'writable')
                self.assertEqual(imported['rows'], 1)
                await client.call_tool('iris_create_index', {'table': self.created,
                    'column': 'Number', 'index': 'FleetNumberIdx', 'server': 'writable'})
                with self.assertRaisesRegex(Exception, 'Unknown server'):
                    await client.call_tool('iris_tables', {'server': 'missing'})
        asyncio.run(check())
        self.assertTrue(self.admins['writable'].table_exists(self.created))
        self.assertFalse(self.admins['readonly'].table_exists(self.created))

    def test_database_permissions_hold_without_mcp_guard(self):
        # Deliberately disable the TOML guard: IRIS still must deny the reader's DDL.
        self.write_config(read_only=False)
        async def check():
            async with self.client() as client:
                with self.assertRaisesRegex(Exception, 'operation failed'):
                    await client.call_tool('iris_create_table', {'server': 'readonly',
                        'table': self.created, 'columns': {'Number': 'INT'}})
        asyncio.run(check())
        for name, admin in self.admins.items():
            with IRIStool(host='localhost', port=admin.port, namespace='USER',
                          username=self.users[name], password=self.password) as db:
                for statement in (
                    f'INSERT INTO SQLUser.{self.table} (Number, Marker) VALUES (2, \'changed\')',
                    f"UPDATE SQLUser.{self.table} SET Marker = 'changed' WHERE Number = 1",
                    f'DELETE FROM SQLUser.{self.table} WHERE Number = 2',
                ):
                    if name == 'readonly':
                        with self.subTest(statement=statement), self.assertRaisesRegex(Exception, '(?i)privilege'):
                            self.sql(db, statement)
                        db.conn.rollback()
                    else:
                        self.sql(db, statement)
        self.assertFalse(self.admins['readonly'].table_exists(self.created))
        self.assertEqual(self.admins['readonly'].fetch(
            f'SELECT Marker FROM SQLUser.{self.table}').iloc[0, 0], 'reader')
