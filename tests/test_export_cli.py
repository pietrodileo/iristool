import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from iristool.cli import _connection, main_export


class ExportCLITests(unittest.TestCase):
    def test_table_schema_output_and_overwrite(self):
        for options, schema, overwrite in [([], 'SQLUser', False),
                                           (['--schema', 'Reports', '--overwrite'], 'Reports', True)]:
            with self.subTest(schema=schema):
                connection = MagicMock()
                db = connection.__enter__.return_value
                db.export_table.return_value = Path('people.csv')
                with patch('iristool.cli._connection', return_value=connection), \
                        patch('sys.argv', ['iristool-export', 'People', 'people.csv', *options]), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    main_export()
                db.export_table.assert_called_once_with('People', 'people.csv',
                                                        table_schema=schema, overwrite=overwrite)
                connection.__exit__.assert_called_once()
                self.assertIn('Exported to people.csv', output.getvalue())

    def test_export_errors_exit_nonzero_and_close_connection(self):
        for error in (FileExistsError('already exists'), ValueError('invalid format'),
                      RuntimeError('SQL failed'), ImportError('Install iristool[excel]')):
            with self.subTest(error=type(error).__name__):
                connection = MagicMock()
                connection.__enter__.return_value.export_table.side_effect = error
                with patch('iristool.cli._connection', return_value=connection), \
                        patch('sys.argv', ['iristool-export', 'People', 'people.csv']), \
                        contextlib.redirect_stderr(io.StringIO()) as output, \
                        self.assertRaises(SystemExit) as raised:
                    main_export()
                self.assertEqual(raised.exception.code, 1)
                self.assertIn(f'Export failed: {error}', output.getvalue())
                connection.__exit__.assert_called_once()

    def test_required_arguments_checked_before_connection(self):
        with patch('iristool.cli._connection') as connect, \
                patch('sys.argv', ['iristool-export', 'People']), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main_export()
        self.assertEqual(raised.exception.code, 2)
        connect.assert_not_called()

    def test_shared_connection_reads_environment(self):
        settings = {'IRIS_HOST': 'test-host', 'IRIS_PORT': '9091', 'IRIS_NAMESPACE': 'TEST',
                    'IRIS_USER': 'test-user', 'IRIS_PASSWORD': 'test-password'}
        with patch.dict('os.environ', settings, clear=True), patch('iristool.cli.IRIStool') as tool:
            _connection()
        tool.assert_called_once_with(host='test-host', port='9091', namespace='TEST',
                                     username='test-user', password='test-password')
