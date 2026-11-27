"""Index SQL, validation and DataFrame dispatch without a database."""
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from test_iristool import disconnected_tool


class IndexTests(unittest.TestCase):
    def test_ordered_columns_and_legacy_positional_arguments(self):
        for kind, prefix in [('index', ''), ('unique', 'unique '), ('bitmap', 'bitmap ')]:
            with self.subTest(kind=kind):
                db, cursor = disconnected_tool()
                db.index_exists = Mock(return_value=False)
                db.create_index('Pair', 'Data', columns=['Second', 'First'], index_type=kind)
                cursor.execute.assert_called_once_with(
                    f'CREATE {prefix}INDEX "Pair" ON SQLUser.Data("Second", "First")')
                db.index_exists.assert_called_once_with('Data', 'Pair', 'SQLUser')
                db.conn.commit.assert_called_once()
        db, cursor = disconnected_tool()
        db.index_exists = Mock(return_value=False)
        db.create_index('Single', 'Data', 'First', 'unique', 'Other')
        cursor.execute.assert_called_once_with('CREATE unique INDEX "Single" ON Other.Data("First")')

    def test_invalid_definitions_do_not_access_database(self):
        invalid = [{}, {'column_name': 'A', 'columns': ['B']}, {'columns': []},
                   {'columns': 'A,B'}, {'columns': ('A', 'B')}, {'columns': ['A', 'a']},
                   {'columns': ['A', 1]}, {'columns': ['A', 'B; DROP TABLE Data']},
                   {'column_name': 'A,B'}, {'columns': ['A', 'B'], 'index_type': 'bitslice'},
                   {'columns': ['A', 'B'], 'index_type': 'columnar'},
                   {'columns': ['A'], 'index_type': 'ordinary'}]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                db, _ = disconnected_tool()
                with self.assertRaises(ValueError):
                    db.create_index('Pair', 'Data', **kwargs)
                db.conn.cursor.assert_not_called()

    def test_index_failure_rolls_back_and_closes_cursor(self):
        db, cursor = disconnected_tool()
        db.index_exists = Mock(return_value=False)
        cursor.execute.side_effect = RuntimeError('index build failed')
        with self.assertRaises(RuntimeError):
            db.create_index('Pair', 'Data', columns=['A', 'B'])
        db.conn.rollback.assert_called_once()
        db.conn.commit.assert_not_called()
        cursor.close.assert_called_once()

    def test_dataframe_normalizes_and_dispatches_composite_and_single_indexes(self):
        db, _ = disconnected_tool()
        frame = pd.DataFrame({'First Field': [1], 'Second.Field': [2]})
        with patch.object(db, 'create_table'), patch.object(db, 'create_index') as create:
            db.df_to_table(frame, 'Data', indices=[
                {'columns': ['Second.Field', 'First Field'], 'type': 'unique'},
                {'column': 'First Field', 'name': 'Single'},
            ])
        self.assertEqual(create.call_args_list[0].kwargs,
                         dict(index_name='Data_Second_Field_First_Field_unique', table_name='Data',
                              columns=['Second_Field', 'First_Field'], index_type='unique',
                              table_schema='SQLUser'))
        self.assertEqual(create.call_args_list[1].kwargs['columns'], ['First_Field'])

    def test_bad_dataframe_indexes_fail_before_replacing_table(self):
        for index in [{'columns': []}, {'columns': ['A', 'a']}, {'columns': ['Missing']},
                      {'column': 'A', 'columns': ['B']}, {'columns': 'A,B'},
                      {'columns': ['A', None]}, {'columns': ['A', 'B'], 'type': 'hnsw'},
                      {'columns': ['A', 'B'], 'type': 'bitslice'},
                      {'columns': ['A', 'B'], 'type': 'columnar'}]:
            with self.subTest(index=index):
                db, _ = disconnected_tool()
                with self.assertRaises(ValueError):
                    db.df_to_table(pd.DataFrame({'A': [1], 'B': [2]}), 'Data',
                                   indices=[index], exist_ok=True, drop_if_exists=True)
                db.conn.cursor.assert_not_called()

    def test_describe_returns_index_positions(self):
        db, cursor = disconnected_tool()
        cursor.description = [('INDEX_NAME',), ('COLUMN_NAME',), ('PRIMARY_KEY',),
                              ('NON_UNIQUE',), ('ORDINAL_POSITION',)]
        cursor.fetchall.side_effect = [[], [('Pair', 'B', 0, 1, 1), ('Pair', 'A', 0, 1, 2)]]
        metadata = db.describe_table('Data')
        self.assertEqual([row['ORDINAL_POSITION'] for row in metadata['indexes']], [1, 2])
        self.assertIn('ORDER BY index_name, ORDINAL_POSITION', cursor.execute.call_args.args[0])
