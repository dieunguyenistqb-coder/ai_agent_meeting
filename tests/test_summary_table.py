"""Summary table presentation and selection without provider requests."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import streamlit as st
from src import pipeline
from test_app import make_app, navigate


class SummaryTableTests(unittest.TestCase):
    def test_columns_filter_missing_values_and_no_mutation(self):
        with patch.object(pipeline, 'call_llm') as llm:
            at = make_app()
            final = {'meeting_id': 'TEST', 'items': [
                {'item_id': 'ITEM001', 'content_type': 'task_candidate',
                 'description': 'First task', 'owners': ['A', 'B'], 'deadline': None,
                 'depends_on': ['ITEM002'], 'expected_decision': 'confirmed'},
                {'item_id': 'ITEM002', 'content_type': 'information',
                 'description': 'Background', 'owners': [], 'deadline': None,
                 'expected_decision': 'not_task'}]}
            original = deepcopy(final)
            at.session_state['final_object'] = final
            navigate(at, 'Extraction Result')
            self.assertFalse(at.exception)
            table = at.dataframe[0].value
            self.assertEqual(list(table.columns), ['item_id', 'content_type', 'description',
                'owners', 'deadline', 'commitment', 'depends_on', 'expected_decision'])
            self.assertEqual(len(table), 2)
            self.assertEqual(table.iloc[0]['owners'], 'A, B')
            self.assertEqual(table.iloc[0]['depends_on'], 'ITEM002')
            self.assertEqual(table.iloc[1]['owners'], '-')
            self.assertEqual(table.iloc[1]['deadline'], '-')
            self.assertEqual(table.iloc[1]['depends_on'], '-')
            at.selectbox[0].select('information').run()
            self.assertEqual(at.dataframe[0].value['item_id'].tolist(), ['ITEM002'])
            self.assertEqual([m.value for m in at.metric], ['2', '1', '0', '1'])
            at.selectbox[0].select('decision').run()
            self.assertTrue(at.dataframe[0].value.empty)
            self.assertEqual(at.session_state['final_object'], original)
            llm.assert_not_called()

    def test_row_selection_shows_selected_card_first_and_keeps_all(self):
        real_dataframe = st.dataframe
        def select_second(*args, **kwargs):
            real_dataframe(*args, **kwargs)
            return SimpleNamespace(selection=SimpleNamespace(rows=[1]))
        with patch.object(pipeline, 'call_llm') as llm:
            at = make_app()
            next(b for b in at.button if b.label == 'Tải dữ liệu demo').click().run()
            original = deepcopy(at.session_state['final_object'])
            with patch('streamlit.dataframe', side_effect=select_second):
                navigate(at, 'Extraction Result')
            self.assertFalse(at.exception)
            descriptions = [i['description'] for i in original['items']]
            shown = [t.value for t in at.text if t.value in descriptions]
            self.assertEqual(shown, [descriptions[1], descriptions[0], descriptions[2]])
            self.assertTrue(any(c.value == 'Item đang chọn' for c in at.caption))
            self.assertEqual(at.session_state['final_object'], original)
            llm.assert_not_called()
