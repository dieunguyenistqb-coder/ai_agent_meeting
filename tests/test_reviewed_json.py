"""Review snapshots preserve extraction evidence and the n8n payload schema."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from services.review_service import ReviewService
from services.store import task_key
from ui.demo import load_demo, refresh_views, reset_session
from ui.review_state import refresh_reviewed_json
from test_app import make_app, navigate


class ReviewedJsonTests(unittest.TestCase):
    def test_review_actions_preserve_original_and_schema(self):
        for action in ('confirm', 'edit', 'reject'):
            with self.subTest(action=action):
                state = {}
                load_demo(state)
                original = deepcopy(state['final_json'])
                self.assertIsNone(state['reviewed_json'])
                changes = dict(description='Edited task', owners=['Lan'], deadline='2026-10-02')
                ReviewService(state['demo_store']).decide(
                    task_key('DEMO', 'ITEM002'), action, changes if action == 'edit' else None)
                refresh_views(state)
                reviewed = state['reviewed_json']
                self.assertEqual(state['final_json'], original)
                self.assertEqual(state['final_object'], original)
                self.assertEqual(set(reviewed), set(original))
                for before, after in zip(original['items'], reviewed['items']):
                    self.assertEqual(set(before), set(after))
                    if before['item_id'] != 'ITEM002':
                        self.assertEqual(before, after)
                item = reviewed['items'][1]
                self.assertEqual(item['expected_decision'], 'not_task' if action == 'reject' else 'confirmed')
                self.assertIsNone(item['review_reason'])
                expected = deepcopy(original['items'][1])
                if action == 'edit':
                    expected.update(changes)
                expected.update(expected_decision=item['expected_decision'], review_reason=None)
                self.assertEqual(item, expected)
                refresh_views(state)
                self.assertEqual(state['reviewed_json'], reviewed)
                state['final_object'] = None
                refresh_reviewed_json(state)
                self.assertIsNone(state['final_json'])
                self.assertIsNone(state['reviewed_json'])
                reset_session(state)
                self.assertNotIn('reviewed_json', state)

    def test_reviewed_payload_is_displayed_and_sent_without_llm_or_policy(self):
        with patch('src.pipeline.call_llm') as llm, patch(
                'src.pipeline.process_transcript') as pipeline, patch(
                'services.n8n_service.requests.post') as post:
            post.return_value.status_code = 200
            at = make_app()
            next(b for b in at.button if b.label == 'Tải dữ liệu demo').click().run()
            original = deepcopy(at.session_state['final_json'])
            navigate(at, 'Human Review')
            next(b for b in at.button if b.label == 'Xác nhận').click().run()
            reviewed = deepcopy(at.session_state['reviewed_json'])
            self.assertEqual(reviewed['items'][1]['expected_decision'], 'confirmed')
            navigate(at, 'Extraction Result')
            self.assertFalse(at.exception)
            self.assertTrue(any('Đã cập nhật sau Human Review' in c.value for c in at.caption))
            self.assertEqual([m.value for m in at.metric], ['3', '3', '0', '0'])
            post.assert_not_called()
            at.button(key='send_to_task_workflow').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(post.call_args.kwargs['json'], reviewed)
            self.assertEqual(at.session_state['final_json'], original)
            llm.assert_not_called()
            pipeline.assert_not_called()

    def test_edit_and_reject_ui_update_outgoing_snapshot(self):
        for action in ('edit', 'reject'):
            with self.subTest(action=action), patch('src.pipeline.call_llm') as llm:
                at = make_app()
                next(b for b in at.button if b.label == 'Tải dữ liệu demo').click().run()
                original = deepcopy(at.session_state['final_json'])
                navigate(at, 'Human Review')
                if action == 'edit':
                    at.text_area[0].set_value('Nội dung đã sửa')
                    next(t for t in at.text_input if 'Người phụ trách' in t.label).set_value('Lan, Nam')
                    next(b for b in at.button if b.label == 'Lưu và xác nhận').click().run()
                else:
                    next(b for b in at.button if b.label == 'Từ chối').click().run()
                self.assertFalse(at.exception)
                item = at.session_state['reviewed_json']['items'][1]
                self.assertEqual(item['expected_decision'], 'confirmed' if action == 'edit' else 'not_task')
                self.assertIsNone(item['review_reason'])
                if action == 'edit':
                    self.assertEqual(item['description'], 'Nội dung đã sửa')
                    self.assertEqual(item['owners'], ['Lan', 'Nam'])
                self.assertEqual(at.session_state['final_json'], original)
                llm.assert_not_called()
