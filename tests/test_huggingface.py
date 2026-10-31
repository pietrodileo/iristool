import contextlib
import io
import unittest
from unittest.mock import Mock, patch

try:
    from datasets import Dataset
except ImportError:
    Dataset = None
import pandas as pd

from iristool.integrations.huggingface import import_dataset
from iristool.integrations.cli import main_huggingface as main


@unittest.skipIf(Dataset is None, "requires iristool[huggingface]")
class HuggingFaceTests(unittest.TestCase):
    def setUp(self):
        loader = patch("datasets.load_dataset")
        self.load = loader.start()
        self.addCleanup(loader.stop)
        self.load.return_value = Dataset.from_dict({
            "Name": ["Ada", "Grace"], "Age": [36, 40], "Score": [1.5, None],
        })
        self.db = Mock()
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_download_to_pandas_passes_types_and_nulls_to_iristool(self):
        result = import_dataset(self.db, "owner/people")
        self.load.assert_called_once_with("owner/people", name=None, split="train", revision=None)
        frame, name = self.db.df_to_table.call_args.args
        self.assertEqual(name, "HF_people_train")
        self.assertTrue(pd.api.types.is_integer_dtype(frame["Age"]))
        self.assertTrue(pd.api.types.is_float_dtype(frame["Score"]))
        self.assertTrue(pd.isna(frame.loc[1, "Score"]))
        self.assertEqual(result, {"SQLUser.HF_people_train": 2})
        self.assertEqual(self.db.df_to_table.call_args.kwargs,
                         {"table_schema": "SQLUser", "exist_ok": False, "drop_if_exists": False})

    def test_explicit_token_and_anonymous_mode(self):
        for token in ('workspace-token', False):
            self.load.reset_mock()
            import_dataset(self.db, "owner/people", token=token)
            self.assertEqual(self.load.call_args.kwargs['token'], token)

    def test_url_config_revision_split_and_connection_options(self):
        result = import_dataset(self.db, "https://huggingface.co/datasets/owner/people/", config="subset",
                                split="test[:10]", revision="abc123", table="People",
                                replace=True)
        self.load.assert_called_once_with("owner/people", name="subset", split="test[:10]", revision="abc123")
        self.assertTrue(self.db.df_to_table.call_args.kwargs["exist_ok"])
        self.assertTrue(self.db.df_to_table.call_args.kwargs["drop_if_exists"])
        self.assertEqual(result, {"SQLUser.People": 2})

    def test_nested_values_fail_before_database_connection(self):
        for values in ([[1, 2], [3]], [{"text": "hello"}, {"text": "world"}]):
            self.load.return_value = Dataset.from_dict({"nested": values})
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "nested or media"):
                import_dataset(self.db, "owner/data", replace=True)
        self.db.df_to_table.assert_not_called()

    def test_bad_inputs_fail_before_download(self):
        for dataset, options in (("../local", {}), ("/tmp/local", {}),
                                 ("https://evil.test/datasets/a/b", {}),
                                 ("https://huggingface.co/owner/model", {}),
                                 ("a/b/tree/main", {}), ("a/b", {"split": ""}),
                                 ("a/b", {"table": "Bad;DROP"}), ("a/b", {"schema": "bad.schema"})):
            with self.subTest(dataset=dataset, options=options), self.assertRaises(ValueError):
                import_dataset(self.db, dataset, **options)
        self.load.assert_not_called()

    def test_authentication_failure_propagates_without_database_write(self):
        self.load.side_effect = RuntimeError("Access denied: log in")
        with self.assertRaisesRegex(RuntimeError, "Access denied"):
            import_dataset(self.db, "owner/private")
        self.db.df_to_table.assert_not_called()

    def test_cli_forwards_options(self):
        with patch("iristool.integrations.cli._connection", return_value=Mock(__enter__=Mock(return_value=self.db), __exit__=Mock(return_value=False))), patch("sys.argv", ["iristool-hf", "owner/data", "--split", "test", "--config", "en",
                                "--revision", "v1", "--table", "Reviews", "--replace"]):
            main()
        self.load.assert_called_once_with("owner/data", name="en", split="test", revision="v1")
        self.assertEqual(self.db.df_to_table.call_args.args[1], "Reviews")

    def test_cli_failure_is_nonzero(self):
        self.load.side_effect = RuntimeError("Access denied")
        with patch("iristool.integrations.cli._connection", return_value=Mock(__enter__=Mock(return_value=self.db), __exit__=Mock(return_value=False))), patch("sys.argv", ["iristool-hf", "owner/data"]), contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Access denied", err.getvalue())


if __name__ == "__main__":
    unittest.main()
