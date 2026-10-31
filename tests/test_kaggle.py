import contextlib
import io
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

import pandas as pd

from iristool.integrations.kaggle import _handle, import_dataset
from iristool.integrations.cli import main_kaggle as main


@unittest.skipUnless(importlib.util.find_spec("kagglehub"), "requires iristool[kaggle]")
class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        downloader = patch("kagglehub.dataset_download", return_value=str(self.folder))
        self.download = downloader.start()
        self.addCleanup(downloader.stop)
        self.db = Mock()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def csv(self, name="people.csv", content="Name,Age,Score\nAda,36,1.5\nGrace,40,\n"):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_csv_passes_pandas_types_and_nulls_to_iristool(self):
        self.csv()
        result = import_dataset(self.db, "https://www.kaggle.com/datasets/owner/data?select=people.csv")
        self.download.assert_called_once_with("owner/data")
        frame, table = self.db.df_to_table.call_args.args
        self.assertEqual(table, "people")
        self.assertTrue(pd.api.types.is_integer_dtype(frame["Age"]))
        self.assertTrue(pd.api.types.is_float_dtype(frame["Score"]))
        self.assertTrue(pd.isna(frame.loc[1, "Score"]))
        self.db.df_to_table.assert_called_once_with(frame, "people", table_schema="SQLUser",
                                                  exist_ok=False, drop_if_exists=False)
        self.assertEqual(result, {"SQLUser.people": 2})

    def test_workspace_token_uses_isolated_download(self):
        import json
        self.csv()
        with patch('iristool.integrations.kaggle.subprocess.run') as run:
            run.return_value = Mock(returncode=0, stdout=json.dumps(str(self.folder)))
            import_dataset(self.db, 'owner/data', token='workspace-secret')
            self.assertEqual(json.loads(run.call_args.kwargs['input'])['token'], 'workspace-secret')
            self.assertNotIn('workspace-secret', str(run.call_args.args))
            self.download.assert_not_called()
            run.return_value = Mock(returncode=1, stdout='', stderr='workspace-secret')
            with self.assertRaisesRegex(RuntimeError, 'workspace token') as error:
                import_dataset(self.db, 'owner/data', token='workspace-secret')
            self.assertNotIn('workspace-secret', str(error.exception))

    def test_child_sets_credentials_before_download(self):
        import json
        from iristool.integrations._kaggle_download import main as download_main
        with patch('sys.stdin', io.StringIO(json.dumps({'dataset': 'owner/data', 'file': None,
                                                     'token': 'child-secret'}))), patch('kagglehub.config.set_kaggle_api_token') as setter:
            download_main()
        setter.assert_called_once_with('child-secret')
        self.download.assert_called_once_with('owner/data')

    def test_all_files_nested_tsv_and_name_normalization(self):
        self.csv("nested/2026-sales.TSV", "Order #\tTotal ($)\n7\t3.5\n")
        self.csv()
        (self.folder / "readme.txt").write_text("ignored")
        result = import_dataset(self.db, "owner/data")
        self.assertEqual(result, {"SQLUser.Data_2026_sales": 1, "SQLUser.people": 2})
        frame = self.db.df_to_table.call_args_list[0].args[0]
        self.assertEqual(list(frame.columns), ["Order__", "Total____"])
        self.assertEqual(frame.loc[0, "Total____"], 3.5)

    def test_selected_file_replacement_and_pandas_options(self):
        path = self.csv("sales.csv", "Zip;Date\n00123;2026-10-24\n")
        self.download.return_value = str(path)
        import_dataset(self.db, "owner/data/versions/2", file="sales.csv", table="Sales", replace=True,
                       schema="SQLUser", read_csv_kwargs={"sep": ";", "dtype": {"Zip": "string"},
                                                        "parse_dates": ["Date"]})
        self.download.assert_called_once_with("owner/data/versions/2", path="sales.csv")
        frame = self.db.df_to_table.call_args.args[0]
        self.assertEqual(frame.loc[0, "Zip"], "00123")
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(frame["Date"]))
        self.assertTrue(self.db.df_to_table.call_args.kwargs["drop_if_exists"])
        self.assertTrue(self.db.df_to_table.call_args.kwargs["exist_ok"])

    def test_no_csv_or_ambiguous_table_fails_before_connecting(self):
        with self.assertRaisesRegex(ValueError, "No CSV/TSV"):
            import_dataset(self.db, "owner/data")
        self.csv()
        self.csv("other.csv")
        with self.assertRaisesRegex(ValueError, "single file"):
            import_dataset(self.db, "owner/data", table="Target")
        self.db.df_to_table.assert_not_called()

    def test_colliding_table_names_fail_before_connecting(self):
        self.csv("a/b.csv")
        self.csv("c/B.csv")
        with self.assertRaisesRegex(ValueError, "duplicate table"):
            import_dataset(self.db, "owner/data", replace=True)
        self.db.df_to_table.assert_not_called()

    def test_colliding_columns_fail_before_writing(self):
        self.csv(content="a-b,a_b\n1,2\n")
        with self.assertRaisesRegex(ValueError, "Column names collide"):
            import_dataset(self.db, "owner/data", replace=True)
        self.db.df_to_table.assert_not_called()

    def test_invalid_inputs_fail_before_download(self):
        for options in ({"file": "../secret.csv"}, {"file": "/secret.csv"}, {"file": "x.parquet"},
                        {"file": ""}, {"file": "..\\secret.csv"},
                        {"table": "SQLUser.Bad"}, {"schema": "Bad;DROP"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                import_dataset(self.db, "owner/data", **options)
        self.download.assert_not_called()

    def test_handle_validation(self):
        self.assertEqual(_handle("https://www.kaggle.com/datasets/a/b/versions/2"), "a/b/versions/2")
        for handle in ("../data", "owner", "owner/data/extra", "https://evil.test/datasets/a/b",
                       "https://www.kaggle.com/competitions/titanic", "a/b/versions/0"):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                import_dataset(self.db, handle)
        self.download.assert_not_called()

    def test_database_error_propagates_without_closing_caller_connection(self):
        self.csv()
        self.db.df_to_table.side_effect = RuntimeError("insertion failed")
        with self.assertRaisesRegex(RuntimeError, "insertion failed"):
            import_dataset(self.db, "owner/data")
        self.db.close.assert_not_called()

    def test_cli_returns_nonzero_for_download_error(self):
        self.download.side_effect = RuntimeError("access denied")
        with patch("iristool.integrations.cli._connection", return_value=MagicMock()), patch("sys.argv", ["iristool-kaggle", "owner/data"]), contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("access denied", err.getvalue())


if __name__ == "__main__":
    unittest.main()
