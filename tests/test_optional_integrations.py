import unittest
from unittest.mock import Mock, patch

from iristool.integrations import import_huggingface, import_kaggle


class OptionalDependencyTests(unittest.TestCase):
    def test_missing_download_libraries_give_install_instructions(self):
        db = Mock()
        for importer, module, extra in ((import_kaggle, "kagglehub", "kaggle"),
                                        (import_huggingface, "datasets", "huggingface")):
            with self.subTest(extra=extra), patch.dict("sys.modules", {module: None}):
                with self.assertRaisesRegex(ImportError, rf"iristool\[{extra}\]"):
                    importer(db, "owner/dataset")
        db.df_to_table.assert_not_called()
