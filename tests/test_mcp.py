import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import pandas as pd

MCP_AVAILABLE = importlib.util.find_spec('fastmcp') is not None
if MCP_AVAILABLE:
    from fastmcp import Client
    from fastmcp.exceptions import ToolError
    from iristool.mcp_config import load_config
    from iristool.mcp_server import create_server, Fleet


CONFIG = '''default_server = "dev"
[instance.dev]
host = "localhost"
port = 9091
namespace = "USER"
username = "developer"
password_env = "IRISTOOL_TEST_PASSWORD"
[instance.prod]
host = "other.example.com"
namespace = "REPORTING"
username = "reader"
password = "prod-secret"
read_only = true
'''


@unittest.skipUnless(MCP_AVAILABLE, 'requires iristool[mcp]')
class ConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root / '.iristool.toml'
        self.path.write_text(CONFIG)
        environment = patch.dict(os.environ, {'IRISTOOL_TEST_PASSWORD': 'dev-secret'})
        environment.start()
        self.addCleanup(environment.stop)

    def test_fleet_defaults_and_secret_repr(self):
        config = load_config(self.root)
        self.assertEqual(config.default_server, 'dev')
        self.assertEqual(config.connections['dev'].port, 9091)
        self.assertEqual(config.connections['prod'].port, 1972)
        self.assertTrue(config.connections['prod'].read_only)
        self.assertNotIn('dev-secret', repr(config))
        self.assertNotIn('prod-secret', repr(config))

    def test_provider_tokens_are_workspace_scoped_and_hidden(self):
        self.path.write_text(CONFIG + '\n[providers.huggingface]\ntoken="hf-private"\n'
                             '[providers.kaggle]\ntoken_env="WORKSPACE_KAGGLE"\n')
        with patch.dict(os.environ, {'WORKSPACE_KAGGLE': 'kg-private'}):
            config = load_config(self.root)
        self.assertEqual(config.huggingface_token, 'hf-private')
        self.assertEqual(config.kaggle_token, 'kg-private')
        self.assertNotIn('hf-private', repr(config))
        self.assertNotIn('kg-private', repr(config))
        for settings in ('token=""', 'token="secret"\ntoken_env="X"', 'unknown="x"',
                         'token_env="MISSING_PROVIDER_TEST"'):
            self.path.write_text(CONFIG + '\n[providers.kaggle]\n' + settings)
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                load_config(self.root)

    def test_custom_relative_and_absolute_filenames(self):
        other = self.root / 'fleet.toml'
        self.path.rename(other)
        for name in ('fleet.toml', str(other)):
            self.assertEqual(load_config(self.root, name).path, other)
        with self.assertRaises(FileNotFoundError):
            load_config(self.root, 'missing.toml')

    def test_home_fallback_and_workspace_precedence(self):
        home = self.root / 'home'
        home.mkdir()
        (home / '.iristool.toml').write_text(CONFIG.replace('default_server = "dev"', 'default_server = "prod"'))
        with patch('pathlib.Path.home', return_value=home):
            self.assertEqual(load_config(self.root).default_server, 'dev')
            self.path.unlink()
            self.assertEqual(load_config(self.root).default_server, 'prod')

    def test_path_escape_and_symlinks_are_rejected(self):
        config = load_config(self.root)
        self.assertEqual(config.local_path('data.csv'), self.root / 'data.csv')
        (self.root / 'escape').symlink_to(self.root.parent, target_is_directory=True)
        for path in ('../data.csv', 'escape/data.csv', '.iristool.toml', 'other.toml'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                config.local_path(path)

    def test_invalid_config_does_not_open_connections(self):
        variants = [CONFIG.replace('9091', '0'), CONFIG.replace('9091', 'true'),
                    CONFIG.replace('read_only = true', 'read_only = "true"'),
                    CONFIG.replace('default_server = "dev"', 'default_server = "missing"'),
                    CONFIG.replace('password_env = "IRISTOOL_TEST_PASSWORD"', 'password_env = "MISSING_PASSWORD_TEST"'),
                    CONFIG.replace('password_env = "IRISTOOL_TEST_PASSWORD"', 'password = "x"\npassword_env = "IRISTOOL_TEST_PASSWORD"'),
                    CONFIG.replace('host = "localhost"', 'host = ""'),
                    CONFIG.replace('port = 9091', 'web_port = 9091')]
        for content in variants:
            self.path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                load_config(self.root)

    def test_single_connection_can_omit_default(self):
        self.path.write_text(CONFIG.split('[instance.prod]')[0].replace('default_server = "dev"\n', ''))
        self.assertEqual(load_config(self.root).default_server, 'dev')

    def test_real_stdio_handshake_tool_discovery_and_error(self):
        from fastmcp.client.transports import StdioTransport
        async def check():
            transport = StdioTransport(command=sys.executable,
                                       args=['-m', 'iristool.mcp_server', '--workspace', str(self.root)],
                                       env={'IRISTOOL_TEST_PASSWORD': 'dev-secret'}, log_file=self.root / 'stdio.log')
            async with Client(transport) as client:
                self.assertEqual(len(await client.list_tools()), 9)
                result = (await client.call_tool('iris_servers', {})).data
                self.assertEqual(result['default_server'], 'dev')
                self.assertNotIn('secret', json.dumps(result))
                with self.assertRaisesRegex(Exception, 'read-only'):
                    await client.call_tool('iris_create_table', {
                        'table': 'People', 'columns': {'N': 'INT'}, 'server': 'prod'})
        asyncio.run(check())



@unittest.skipUnless(MCP_AVAILABLE, 'requires iristool[mcp]')
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / '.iristool.toml').write_text(CONFIG.replace('password_env = "IRISTOOL_TEST_PASSWORD"', 'password = "dev-secret"') + '\n[providers.kaggle]\ntoken="workspace-kaggle-secret"\n')
        self.config = load_config(self.root)
        self.db = Mock()
        self.db.show_namespace_tables.return_value = pd.DataFrame([{'TABLE_NAME': 'People'}])
        self.db.describe_table.return_value = {'columns': [{'name': 'N'}], 'indices': []}
        self.factory = Mock(return_value=self.db)
        self.server = create_server(self.config, factory=self.factory)
        self.client = Client(self.server)
        await self.client.__aenter__()

    async def asyncTearDown(self):
        await self.client.__aexit__(None, None, None)

    async def test_lazy_connection_reused_and_routed(self):
        result = (await self.client.call_tool('iris_servers', {})).data
        self.assertNotIn('secret', json.dumps(result))
        self.factory.assert_not_called()
        await self.client.call_tool('iris_tables', {})
        await self.client.call_tool('iris_describe_table', {'table': 'People'})
        self.factory.assert_called_once_with(host='localhost', port=9091, namespace='USER',
                                             username='developer', password='dev-secret')
        await self.client.call_tool('iris_tables', {'server': 'prod'})
        self.assertEqual(self.factory.call_args.kwargs['namespace'], 'REPORTING')

    async def test_read_only_blocks_every_database_write_before_connect(self):
        calls = [('iris_create_table', {'table': 'Data', 'columns': {'N': 'INT'}}),
                 ('iris_create_index', {'table': 'Data', 'column': 'N', 'index': 'idx'}),
                 ('iris_import_file', {'table': 'Data', 'path': 'input.csv'}),
                 ('iris_import_huggingface', {'dataset': 'owner/data'}),
                 ('iris_import_kaggle', {'dataset': 'owner/data'})]
        for name, arguments in calls:
            with self.subTest(tool=name), self.assertRaisesRegex(Exception, 'read-only'):
                await self.client.call_tool(name, {**arguments, 'server': 'prod'})
        self.factory.assert_not_called()

    async def test_unknown_server_does_not_fall_back(self):
        with self.assertRaisesRegex(Exception, 'Unknown server'):
            await self.client.call_tool('iris_tables', {'server': 'typo'})
        self.factory.assert_not_called()

    async def test_import_and_export_dispatch_and_path_checks(self):
        with patch('iristool.transfer.import_file', return_value=42) as importer:
            # create_server imports the helpers once, so create a fresh server under the patch.
            async with Client(create_server(self.config, factory=self.factory)) as client:
                result = (await client.call_tool('iris_import_file', {'path': 'input.csv', 'table': 'Data'})).data
                self.assertEqual(result['rows'], 42)
                self.assertEqual(importer.call_args.args[1], self.root / 'input.csv')
                with self.assertRaisesRegex(Exception, 'inside'):
                    await client.call_tool('iris_import_file', {'path': '../input.csv', 'table': 'Data'})
        with patch('iristool.transfer.export_file', return_value={'path': str(self.root / 'out.csv'), 'rows': 2}):
            async with Client(create_server(self.config, factory=self.factory)) as client:
                result = (await client.call_tool('iris_export_table', {'path': 'out.csv', 'table': 'Data', 'server': 'prod'})).data
                self.assertEqual(result['rows'], 2)

    async def test_subset_export_is_structured_and_allowed_on_read_only_server(self):
        self.db._identifier.side_effect = lambda name: '"' + name + '"'
        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.description = [('N',)]
        cursor.fetchmany.side_effect = [[(2,)], []]
        self.db.conn.cursor.return_value = cursor
        from iristool import IRIStool
        self.db._identifier.side_effect = IRIStool._identifier
        result = (await self.client.call_tool('iris_export_table', {
            'table': 'Data', 'path': 'subset.json', 'server': 'prod', 'columns': ['N'],
            'filters': [{'column': 'N', 'op': '>=', 'value': 2}],
            'order_by': [{'column': 'N', 'direction': 'DESC'}], 'limit': 1})).data
        self.assertEqual(result['rows'], 1)
        self.assertEqual(json.loads((self.root / 'subset.json').read_text()), [{'N': 2}])
        self.assertEqual(cursor.execute.call_args.args,
                         ('SELECT TOP 1 "N" FROM "SQLUser"."Data" WHERE "N" >= ? ORDER BY "N" DESC', [2]))
        self.db.conn.commit.assert_not_called()
        for limit in (True, '1', 1.5, 0):
            with self.subTest(limit=limit), self.assertRaises(Exception):
                await self.client.call_tool('iris_export_table', {
                    'table': 'Data', 'path': 'bad.json', 'limit': limit})
        self.assertFalse((self.root / 'bad.json').exists())

    async def test_create_table_index_and_dataset_dispatch(self):
        await self.client.call_tool('iris_create_table', {'table': 'Data', 'columns': {'N': 'INT'}})
        self.db.create_table.assert_called_once_with('Data', {'N': 'INT'}, table_schema='SQLUser', check_exists=True)
        await self.client.call_tool('iris_create_index', {'table': 'Data', 'column': 'N', 'index': 'idx'})
        self.db.create_index.assert_called_once_with('idx', 'Data', 'N', index_type='index', table_schema='SQLUser')
        for name, target in [('iris_import_huggingface', 'import_huggingface'), ('iris_import_kaggle', 'import_kaggle')]:
            with patch('iristool.integrations.' + target, return_value={'SQLUser.Data': 150}):
                result = (await self.client.call_tool(name, {'dataset': 'owner/data'})).data
                self.assertEqual(result['tables'], {'SQLUser.Data': 150})

    async def test_database_error_does_not_expose_credentials(self):
        self.db.show_namespace_tables.side_effect = RuntimeError('password=dev-secret token=provider-secret')
        with self.assertRaises(Exception) as error:
            await self.client.call_tool('iris_tables', {})
        self.assertNotIn('secret', str(error.exception))

    async def test_thread_affinity_and_shutdown(self):
        threads = []
        def factory(**kwargs):
            threads.append(threading.get_ident())
            return self.db
        fleet = Fleet(self.config, factory)
        def operation(db):
            threads.append(threading.get_ident())
            return {'ok': True}
        try:
            await asyncio.gather(*(fleet.call('dev', False, operation) for _ in range(5)))
            self.assertEqual(len(set(threads)), 1)
            self.assertNotEqual(threads[0], threading.get_ident())
        finally:
            await fleet.close()
        self.db.close.assert_called_once()

    async def test_independent_servers_can_run_concurrently(self):
        barrier = threading.Barrier(2, timeout=5)
        fleet = Fleet(self.config, lambda **kwargs: Mock())
        def operation(db):
            barrier.wait()
            return {'ok': True}
        try:
            results = await asyncio.gather(fleet.call('dev', False, operation),
                                           fleet.call('prod', False, operation))
            self.assertEqual({r['server'] for r in results}, {'dev', 'prod'})
        finally:
            await fleet.close()


@unittest.skipUnless(MCP_AVAILABLE, 'requires iristool[mcp]')
class WorkspaceDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.a = self.root / 'workspace A'
        self.b = self.root / 'workspace B'
        for folder, namespace in ((self.a, 'FIRST'), (self.b, 'SECOND')):
            folder.mkdir()
            (folder / '.iristool.toml').write_text(
                '[instance.dev]\nhost="localhost"\nnamespace="' + namespace +
                '"\nusername="developer"\npassword="test-secret"\n')
        self.factory = Mock(side_effect=lambda **kwargs: self.database(kwargs['namespace']))
        self.server = create_server(factory=self.factory)

    @staticmethod
    def database(namespace):
        db = Mock()
        db.show_namespace_tables.return_value = pd.DataFrame([{'namespace': namespace}])
        return db

    async def test_root_changes_route_to_independent_workspace_configs(self):
        active = [self.a]
        async def roots(context):
            return [active[0].as_uri()]
        async with Client(self.server, roots=roots) as client:
            first = (await client.call_tool('iris_servers', {})).data
            self.assertEqual(first['workspace'], str(self.a))
            self.assertEqual(first['servers'][0]['namespace'], 'FIRST')
            first_tables = (await client.call_tool('iris_tables', {})).data
            self.assertEqual(first_tables['tables'], [{'namespace': 'FIRST'}])
            active[0] = self.b
            await client.send_roots_list_changed()
            second = (await client.call_tool('iris_tables', {})).data
            self.assertEqual(second['workspace'], str(self.b))
            self.assertEqual(second['tables'], [{'namespace': 'SECOND'}])
            active[0] = self.a
            await client.call_tool('iris_tables', {})
        self.assertEqual(self.factory.call_count, 2)

    async def test_two_concurrent_clients_keep_workspaces_separate(self):
        async with Client(self.server, roots=[self.a.as_uri()]) as first, \
                Client(self.server, roots=[self.b.as_uri()]) as second:
            results = await asyncio.gather(first.call_tool('iris_tables', {}),
                                           second.call_tool('iris_tables', {}))
            self.assertEqual(results[0].data['workspace'], str(self.a))
            self.assertEqual(results[1].data['workspace'], str(self.b))
            self.assertEqual(results[0].data['tables'], [{'namespace': 'FIRST'}])
            self.assertEqual(results[1].data['tables'], [{'namespace': 'SECOND'}])

    async def test_concurrent_workspace_provider_credentials_are_isolated(self):
        for folder, suffix in ((self.a, 'A'), (self.b, 'B')):
            with (folder / '.iristool.toml').open('a') as stream:
                stream.write(f'\n[providers.huggingface]\ntoken="hf-{suffix}"\n'
                             f'[providers.kaggle]\ntoken="kg-{suffix}"\n')
        for tool, target, prefix in (('iris_import_huggingface', 'import_huggingface', 'hf'),
                                     ('iris_import_kaggle', 'import_kaggle', 'kg')):
            calls = []
            def importer(db, dataset, **options):
                calls.append((db.show_namespace_tables().iloc[0]['namespace'], options['token']))
                return {'SQLUser.Data': 1}
            with patch('iristool.integrations.' + target, side_effect=importer):
                server = create_server(factory=self.factory)
                async with Client(server, roots=[self.a.as_uri()]) as a, Client(server, roots=[self.b.as_uri()]) as b:
                    await asyncio.gather(a.call_tool(tool, {'dataset': 'owner/data'}),
                                         b.call_tool(tool, {'dataset': 'owner/data'}))
            self.assertCountEqual(calls, [('FIRST', prefix + '-A'), ('SECOND', prefix + '-B')])

    async def test_ambiguous_roots_reject_writes_before_connection(self):
        async with Client(self.server, roots=[self.a.as_uri(), self.b.as_uri()]) as client:
            with self.assertRaisesRegex(Exception, 'multiple workspace roots'):
                await client.call_tool('iris_create_table', {'table': 'Data', 'columns': {'N': 'INT'}})
        self.factory.assert_not_called()

    async def test_process_directory_fallback_for_clients_without_roots_or_empty_roots(self):
        with patch('pathlib.Path.cwd', return_value=self.a):
            server = create_server(factory=self.factory)
        for roots in (None, []):
            async with Client(server, roots=roots) as client:
                result = (await client.call_tool('iris_servers', {})).data
                self.assertEqual(result['workspace'], str(self.a))
        self.factory.assert_not_called()

    async def test_explicit_override_takes_precedence_over_client_root(self):
        async with Client(create_server(workspace=self.a), roots=[self.b.as_uri()]) as client:
            result = (await client.call_tool('iris_servers', {})).data
            self.assertEqual(result['workspace'], str(self.a))

    async def test_missing_workspace_config_does_not_use_another_workspace(self):
        (self.b / '.iristool.toml').unlink()
        # No home fallback in this test: neither location contains a config.
        with patch('pathlib.Path.home', return_value=self.b):
            async with Client(self.server, roots=[self.b.as_uri()]) as client:
                self.assertEqual(len(await client.list_tools()), 9)
                with self.assertRaisesRegex(Exception, 'Invalid workspace configuration'):
                    await client.call_tool('iris_tables', {})
        self.factory.assert_not_called()

    async def test_no_args_stdio_uses_client_root_instead_of_process_directory(self):
        from fastmcp.client.transports import StdioTransport
        transport = StdioTransport(command=sys.executable, args=['-m', 'iristool.mcp_server'],
                                   cwd=str(self.root), log_file=self.root / 'stdio.log')
        async with Client(transport, roots=[self.a.as_uri()]) as client:
            result = (await client.call_tool('iris_servers', {})).data
            self.assertEqual(result['workspace'], str(self.a))
            self.assertEqual(result['servers'][0]['namespace'], 'FIRST')

    async def test_nonlocal_file_root_is_rejected(self):
        async with Client(self.server, roots=['file://remote.example.com/workspace']) as client:
            with self.assertRaisesRegex(Exception, 'local file URIs'):
                await client.call_tool('iris_servers', {})
