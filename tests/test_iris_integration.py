"""Live IRIS tests: IRIS_INTEGRATION=1 uv run python -m unittest discover -s tests -v -b."""
import datetime as dt
import os
import unittest
import uuid

import pandas as pd
from iristool import IRIStool


@unittest.skipUnless(os.getenv("IRIS_INTEGRATION") == "1", "requires a running IRIS server")
class IRISIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = IRIStool(
            host=os.getenv("IRIS_HOST", "localhost"),
            port=os.getenv("IRIS_PORT", "9091"),
            namespace=os.getenv("IRIS_NAMESPACE", "USER"),
            username=os.getenv("IRIS_USER", "_SYSTEM"),
            password=os.getenv("IRIS_PASSWORD", "SYS"),
        )
        self.tables = []
        self.views = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        try:
            for view in reversed(self.views):
                self.db.drop_table(view, view_or_table="view")
            for table in reversed(self.tables):
                self.db.drop_table(table)
        finally:
            self.db.close()

    def table(self):
        name = "IRISTool_Test_" + uuid.uuid4().hex[:12]
        self.tables.append(name)
        return name

    def count(self, table):
        return int(self.db.fetch(f"SELECT COUNT(*) AS N FROM SQLUser.{table}").iloc[0, 0])

    def test_dataframe_round_trip(self):
        table = self.table()
        large = 2**53 + 1
        text = "é漢字" * 100
        df = pd.DataFrame({
            "Row Number": [1, 2, 3],
            "Large.Number": pd.Series([large, pd.NA, -large], dtype="Int64"),
            "Ratio": [1.5, float("nan"), 2.5],
            "Flag": pd.Series([True, pd.NA, False], dtype="boolean"),
            "Text": pd.Series([text, pd.NA, "O'Reilly"], dtype="string"),
            "Day": [dt.date(2026, 1, 2), None, dt.date(2026, 3, 4)],
            "Clock": [dt.time(12, 34, 56), None, dt.time(1, 2, 3)],
            "Stamp": pd.to_datetime(["2026-01-02 12:34:56", None, "2026-03-04 01:02:03"]),
        })
        self.db.df_to_table(df, table, primary_key="Row Number", batch_size=2)
        result = self.db.fetch(f"SELECT * FROM SQLUser.{table} ORDER BY Row_Number")
        self.assertEqual(len(result), 3)
        # Query non-null BIGINT alone so pandas does not coerce it to float.
        exact = self.db.fetch(f"SELECT Large_Number FROM SQLUser.{table} WHERE Row_Number = ?", [1])
        self.assertEqual(int(exact.iloc[0, 0]), large)
        self.assertEqual(result.loc[0, "Text"], text)
        self.assertEqual(result.loc[2, "Text"], "O'Reilly")
        for column in ["Large_Number", "Ratio", "Flag", "Text", "Day", "Clock", "Stamp"]:
            self.assertTrue(pd.isna(result.loc[1, column]), column)
        self.assertEqual(result.loc[0, "Day"], dt.date(2026, 1, 2))
        self.assertEqual(result.loc[0, "Clock"], dt.time(12, 34, 56))
        self.assertEqual(result.loc[0, "Stamp"], dt.datetime(2026, 1, 2, 12, 34, 56))
        self.assertEqual(result.loc[0, "Flag"], 1)

    def test_existing_empty_and_replacement(self):
        table = self.table()
        df = pd.DataFrame({"Number": pd.Series(dtype="Int64")})
        self.db.df_to_table(df, table)
        self.assertTrue(self.db.table_exists(table))
        self.assertEqual(self.count(table), 0)
        df = pd.DataFrame({"Number": [42]})
        self.db.df_to_table(df, table, exist_ok=True)
        self.assertEqual(self.count(table), 0)
        self.db.df_to_table(df, table, exist_ok=True, drop_if_exists=True)
        self.assertEqual(self.count(table), 1)
        with self.assertRaises(Exception):
            self.db.df_to_table(df, table)
        self.assertEqual(self.count(table), 1)

    def test_failure_rolls_back_all_batches(self):
        table = self.table()
        with self.assertRaises(RuntimeError):
            self.db.df_to_table(pd.DataFrame({"Number": [1, 2, 1]}), table,
                                primary_key="Number", batch_size=2)
        self.assertEqual(self.count(table), 0)

    def test_sql_helpers(self):
        table = self.table()
        self.db.create_table(table, {"Code": "INT", "Name": "VARCHAR(255)"},
                             constraints=['PRIMARY KEY ("Code")'])
        self.db.insert_row(table, {"Code": 1, "Name": "Ada"})
        self.assertEqual(self.db.insert_many(table, [{"Code": 2, "Name": "Grace"},
                                                    {"Code": 3, "Name": "Linus"}]), 2)
        self.assertEqual(self.db.update(table, {"Name": "Updated"}, {"Code": 1}), 1)
        self.assertEqual(self.db.update_many(table, [({"Name": "Two"}, {"Code": 2}),
                                                     ({"Name": "Three"}, {"Code": 3})]), 2)
        self.db.add_columns(table, {"Note": "VARCHAR(255)"})
        self.db.create_index("Name_Index", table, "Name")
        self.assertTrue(self.db.index_exists(table, "Name_Index"))
        self.assertTrue(self.db.describe_table(table)["columns"])
        self.assertEqual(len(self.db.show_namespace_tables(table_name=table)), 1)
        self.assertFalse(self.db.show_namespace_schemas().empty)
        self.assertEqual(self.db.fetch(f"SELECT Name FROM SQLUser.{table} WHERE Code = ?", [1]).iloc[0, 0], "Updated")
        view = table + "_View"
        self.views.append(view)
        self.db.create_view(view, f"SELECT Code, Name FROM SQLUser.{table}")
        self.assertEqual(len(self.db.fetch(f"SELECT * FROM SQLUser.{view}")), 3)
        self.assertTrue(self.db.views_using_table(table))

    def test_insert_many_constraint_failure_rolls_back(self):
        table = self.table()
        self.db.create_table(table, {"Code": "INT"}, constraints=['PRIMARY KEY ("Code")'])
        with self.assertRaises(Exception):
            self.db.insert_many(table, [{"Code": 1}, {"Code": 1}])
        self.assertEqual(self.count(table), 0)


if __name__ == "__main__":
    unittest.main()
