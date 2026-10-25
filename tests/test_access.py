import contextlib
import importlib.util
import io
import unittest
from unittest.mock import MagicMock, Mock, patch

from iristool.integrations._shared import _raise_if_access_denied
from iristool.integrations import import_kaggle, import_huggingface
from iristool.integrations.cli import main_kaggle, main_huggingface


class AccessTests(unittest.TestCase):
    def test_unrelated_errors_are_not_rewritten(self):
        _raise_if_access_denied(RuntimeError('network failed'), 'https://example.com', 'TOKEN')

    @unittest.skipUnless(importlib.util.find_spec('kagglehub'), 'requires iristool[kaggle]')
    def test_kaggle_permission_error_in_python_and_cli(self):
        from kagglehub.exceptions import KaggleApiHTTPError
        for status in (401, 403):
            exc = KaggleApiHTTPError('denied', response=Mock(status_code=status))
            with self.subTest(status=status), patch('kagglehub.dataset_download', side_effect=exc):
                self.check_failure(import_kaggle, main_kaggle, 'iristool-kaggle',
                                   'https://www.kaggle.com/datasets/owner/data', 'KAGGLE_API_TOKEN')

    @unittest.skipUnless(importlib.util.find_spec('datasets'), 'requires iristool[huggingface]')
    def test_hf_wrapped_gated_error_in_python_and_cli(self):
        from datasets.exceptions import DatasetNotFoundError
        from huggingface_hub.errors import GatedRepoError
        exc = DatasetNotFoundError('gated dataset')
        exc.__cause__ = GatedRepoError('access pending', response=Mock(status_code=403))
        with patch('datasets.load_dataset', side_effect=exc):
            self.check_failure(import_huggingface, main_huggingface, 'iristool-hf',
                               'https://huggingface.co/datasets/owner/data', 'HF_TOKEN')

    @unittest.skipUnless(importlib.util.find_spec('datasets'), 'requires iristool[huggingface]')
    def test_hf_gated_error_without_http_cause(self):
        from datasets.exceptions import DatasetNotFoundError
        exc = DatasetNotFoundError("Dataset 'owner/data' is a gated dataset on the Hub.")
        with patch('datasets.load_dataset', side_effect=exc):
            self.check_failure(import_huggingface, main_huggingface, 'iristool-hf',
                               'https://huggingface.co/datasets/owner/data', 'HF_TOKEN')

    def check_failure(self, importer, main, command, url, token):
        db = Mock()
        with self.assertRaises(PermissionError) as raised:
            importer(db, 'owner/data', replace=True)
        message = str(raised.exception)
        for fragment in ('Dataset processing failed', url, 'browser', 'confirm the terms',
                         'repeat the same command', token):
            self.assertIn(fragment, message)
        db.df_to_table.assert_not_called()
        db.close.assert_not_called()
        connection = MagicMock()
        connection.__enter__.return_value = db
        with patch('iristool.integrations.cli._connection', return_value=connection), \
                patch('sys.argv', [command, 'owner/data', '--replace']), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exited:
                main()
        self.assertEqual(exited.exception.code, 1)
        self.assertIn('repeat the same command', output.getvalue())
        self.assertIn(url, output.getvalue())
        db.df_to_table.assert_not_called()
        connection.__exit__.assert_called_once()
