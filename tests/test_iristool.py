import datetime as dt
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from iristool import IRIStool


def disconnected_tool():
    db = IRIStool.__new__(IRIStool)
    db.conn = Mock()
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    db.conn.cursor.return_value = cursor
    cursor.executemany.side_effect = lambda sql, rows: setattr(cursor, 'rowcount', len(rows))
    return db, cursor


class ImportTests(unittest.TestCase):
    def test_normalized_numeric_type(self):
        self.assertEqual(IRIStool.infer_iris_types(pd.DataFrame({'Total Sales': [42]})),
                         {'Total_Sales': 'INT'})

    def test_nullable_integer_and_empty_object(self):
        df = pd.DataFrame({'Number': pd.Series([pd.NA], dtype='Int64'),
                           'Unknown': pd.Series([None], dtype=object)})
        self.assertEqual(IRIStool.infer_iris_types(df),
                         {'Number': 'INT', 'Unknown': 'VARCHAR(255)'})

    def test_string_dtype_long_values(self):
        df = pd.DataFrame({'Text': pd.Series(['x' * 300, pd.NA], dtype='string')})
        self.assertEqual(IRIStool.infer_iris_types(df), {'Text': 'CLOB'})

    def test_temporal_types_and_boolean(self):
        df = pd.DataFrame({'Day': [dt.date(2025, 1, 1), None],
                           'Clock': [dt.time(12), None],
                           'Stamp': pd.to_datetime(['2025-01-01 12:00', None]),
                           'Flag': pd.Series([True, pd.NA], dtype='boolean')})
        self.assertEqual(IRIStool.infer_iris_types(df),
                         {'Day': 'DATE', 'Clock': 'TIME', 'Stamp': 'DATETIME', 'Flag': 'BIT'})

    def test_overrides_are_not_overwritten_or_mutated(self):
        overrides = {'Total_Sales': 'DECIMAL(12,2)'}
        self.assertEqual(IRIStool.infer_iris_types(pd.DataFrame({'Total Sales': [42]}), overrides), overrides)

    def test_names_and_collisions(self):
        db, _ = disconnected_tool()
        self.assertEqual(db.validate_table_name('My_Table', 'SQLUser'), 'SQLUser.My_Table')
        self.assertEqual(db.validate_table_name('People'), 'People')
        self.assertEqual(db.get_name_and_schema('SQLUser.My_Table'), ('My_Table', 'SQLUser'))
        for name in ['Bad; DROP TABLE People', '', 'A.B.C']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                db.validate_table_name(name, 'SQLUser')
        for columns in [['Total Sales', 'Total.Sales'], ['Name', 'name'], ['bad-name']]:
            with self.subTest(columns=columns), self.assertRaises(ValueError):
                db.df_to_table(pd.DataFrame([[1] * len(columns)], columns=columns), 'Data')
        db.conn.cursor.assert_not_called()

    def test_nulls_precision_and_batches(self):
        db, cursor = disconnected_tool()
        large = 2**53 + 1
        df = pd.DataFrame({'Large Number': pd.Series([large, pd.NA, 1], dtype='Int64'),
                           'Ratio': [1.5, float('nan'), 2.0]})
        db.df_to_table(df, 'Data', batch_size=2)
        batches = [call.args[1] for call in cursor.executemany.call_args_list]
        self.assertEqual([len(batch) for batch in batches], [2, 1])
        self.assertEqual(batches[0][0], (large, 1.5))
        self.assertIs(type(batches[0][0][0]), int)
        self.assertEqual(batches[0][1], (None, None))
        self.assertIn('"Large_Number"', cursor.executemany.call_args.args[0])

    def test_empty_frame_creates_table_without_inserting(self):
        db, cursor = disconnected_tool()
        db.df_to_table(pd.DataFrame({'Number': pd.Series(dtype='int64')}), 'Data')
        cursor.execute.assert_called_once()
        cursor.executemany.assert_not_called()

    def test_failure_rolls_back_and_propagates(self):
        db, cursor = disconnected_tool()
        cursor.executemany.side_effect = ValueError('bad row')
        with self.assertRaisesRegex(RuntimeError, 'bad row'):
            db.df_to_table(pd.DataFrame({'Number': [1]}), 'Data')
        db.conn.rollback.assert_called_once()
        self.assertEqual(db.conn.commit.call_count, 1)  # DDL has already committed.

    def test_rowcount_mismatch_rolls_back(self):
        db, cursor = disconnected_tool()
        cursor.executemany.side_effect = lambda sql, rows: setattr(cursor, 'rowcount', 0)
        with self.assertRaises(RuntimeError):
            db.df_to_table(pd.DataFrame({'Number': [1]}), 'Data')
        db.conn.rollback.assert_called_once()

    def test_validation_precedes_replacement(self):
        db, _ = disconnected_tool()
        db.table_exists = Mock(return_value=True)
        db.drop_table = Mock()
        with self.assertRaises(ValueError):
            db.df_to_table(pd.DataFrame({'Number': [1]}), 'Data', column_types={'Wrong': 'INT'},
                           exist_ok=True, drop_if_exists=True)
        db.drop_table.assert_not_called()

    def test_existing_table_skip(self):
        db, _ = disconnected_tool()
        db.table_exists = Mock(return_value=True)
        db.df_to_table(pd.DataFrame({'Number': [1]}), 'Data', exist_ok=True)
        db.conn.cursor.assert_not_called()

    def test_hnsw_failure_propagates(self):
        db, cursor = disconnected_tool()
        cursor.execute.side_effect = ValueError('index failed')
        with self.assertRaisesRegex(ValueError, 'index failed'):
            db.create_hnsw_index('Data', 'Embedding', 'Embedding_idx')
        db.conn.rollback.assert_called_once()
        cursor.close.assert_called_once()

    def test_driver_error_status_rolls_back(self):
        db, cursor = disconnected_tool()
        cursor.executemany.side_effect = None
        cursor.executemany.return_value = ('constraint violation',)
        cursor.rowcount = -1
        with self.assertRaisesRegex(RuntimeError, 'constraint violation'):
            db.df_to_table(pd.DataFrame({'Number': [1]}), 'Data')
        db.conn.rollback.assert_called_once()

    def test_fetch_without_parameters(self):
        db, cursor = disconnected_tool()
        cursor.fetchall.return_value = [(42,)]
        cursor.description = [('Answer',)]
        result = db.fetch('SELECT 42 AS Answer')
        cursor.execute.assert_called_once_with('SELECT 42 AS Answer')
        self.assertEqual(result.iloc[0, 0], 42)

    def test_insert_many_driver_error_rolls_back(self):
        db, cursor = disconnected_tool()
        cursor.executemany.side_effect = None
        cursor.executemany.return_value = (1, 'constraint violation')
        cursor.rowcount = 1
        with self.assertRaisesRegex(RuntimeError, 'constraint violation'):
            db.insert_many('Data', [{'Number': 1}, {'Number': 1}])
        db.conn.rollback.assert_called_once()
        db.conn.commit.assert_not_called()

    def test_connection_and_context_close(self):
        with patch('iristool.core.iris.dbapi.connect') as connect:
            with IRIStool(port='1972', username='test', password='secret') as db:
                self.assertEqual(db.port, 1972)
            connect.assert_called_once_with(hostname='127.0.0.1', port=1972,
                                           namespace='USER', username='test',
                                           password='secret', autoCommit=False)
            connect.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
