import os
import unittest
from uuid import uuid4

from iristool import IRIStool

from iristool.integrations import import_kaggle as import_dataset
from iristool.integrations import import_huggingface


class IntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("KAGGLE_IRIS_INTEGRATION") == "1", "Opt-in live Kaggle/IRIS test")
    def test_public_kaggle_to_iris(self):
        self.check_import(import_dataset, "uciml/iris", file="Iris.csv")

    @unittest.skipUnless(os.getenv("HF_IRIS_INTEGRATION") == "1", "Opt-in live Hugging Face/IRIS test")
    def test_public_huggingface_to_iris(self):
        self.check_import(import_huggingface, "scikit-learn/iris")

    def check_import(self, importer, dataset, **options):
        table = "DatasetTest_" + uuid4().hex[:12]
        connection = {
            "host": os.getenv("IRIS_HOST", "localhost"),
            "port": int(os.getenv("IRIS_PORT", "9091")),
            "namespace": os.getenv("IRIS_NAMESPACE", "USER"),
            "username": os.getenv("IRIS_USER", "_SYSTEM"),
            "password": os.getenv("IRIS_PASSWORD", "SYS"),
        }
        with IRIStool(**connection) as db:
            try:
                result = importer(db, dataset, table=table, **options)
                self.assertEqual(result, {f"SQLUser.{table}": 150})
                count = db.fetch(f'SELECT COUNT(*) AS N FROM SQLUser."{table}"')
                self.assertEqual(int(count.iloc[0, 0]), 150)
                types = db.fetch("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                                 "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
                                 parameters=["SQLUser", table])
                column_types = dict(types.itertuples(index=False, name=None))
                self.assertIn(column_types["Id"].upper(), {"INTEGER", "INT"})
                self.assertIn(column_types["SepalLengthCm"].upper(), {"DOUBLE", "DOUBLE PRECISION"})
                self.assertIn(column_types["Species"].upper(), {"VARCHAR", "CHARACTER VARYING"})
            finally:
                if db.table_exists(table):
                    db.drop_table(table)
