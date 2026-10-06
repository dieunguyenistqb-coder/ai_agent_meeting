from copy import deepcopy
import unittest
from services.store import new_store, sync_meeting, task_key
from services.review_service import ReviewService
from ui.review_state import build_submission


class ReviewOwnerTests(unittest.TestCase):
    def state(self, owners=None, decision='human_review', content='task_candidate'):
        item = dict(item_id='ITEM001', description='Việc giả lập', owners=owners or [],
                    source_excerpt=['PERSON1: Nhận việc'], content_type=content,
                    commitment='explicit' if content == 'task_candidate' else 'not_applicable',
                    deadline=None, deadline_status='missing', depends_on=[],
                    expected_decision=decision, review_reason=None)
        data = dict(meeting_id='TEST', meeting_date=None, items=[item])
        state = dict(final_object=data, demo_store=new_store())
        sync_meeting(state['demo_store'], data)
        return state, ReviewService(state['demo_store']), task_key('TEST', 'ITEM001')

    def test_no_mutation_when_missing_owner(self):
        for owners in ([], None, ['  ']):
            state, service, key = self.state()
            service.store['items'][key]['owners'] = owners
            before = deepcopy(service.store)
            for action in ('confirm', 'edit'):
                with self.assertRaisesRegex(ValueError, 'Vui lòng chọn người phụ trách'):
                    service.decide(key, action, dict(description='Việc', owners=[], deadline=None))
                self.assertEqual(before, service.store)

    def test_edit_then_confirm_and_stale_repair(self):
        for stale in (False, True):
            state, service, key = self.state(decision='confirmed' if stale else 'human_review')
            if stale:
                service.store['items'][key]['review_status'] = 'confirmed_by_human'
                with self.assertRaisesRegex(ValueError, 'ITEM001'): build_submission(state)
            self.assertEqual(len(service.pending()), 1)
            service.decide(key, 'edit', dict(description='Việc', owners=['PERSON1'], deadline=None))
            self.assertEqual(service.pending(), [])
            self.assertEqual(build_submission(state)['items'][0]['owners'], ['PERSON1'])

    def test_information_decision_do_not_require_owner(self):
        for content in ('information', 'decision'):
            state, service, key = self.state(content=content)
            service.decide(key, 'confirm')
            self.assertEqual(build_submission(state)['items'][0]['owners'], [])

    def test_ui_owner_required_and_submit_blocked(self):
        import json
        from unittest.mock import patch
        from test_app import make_app, upload, response, navigate
        def missing_response(payload):
            data = json.loads(response(payload))
            data['items'][0]['owners'] = []
            return json.dumps(data)
        with patch('streamlit.file_uploader', return_value=upload()), patch('src.pipeline.call_llm', side_effect=missing_response), patch('services.n8n_service.requests.post') as post:
            at = make_app()
            next(b for b in at.button if b.label == 'Run Extraction').click().run()
            navigate(at, 'Human Review')
            self.assertTrue(next(b for b in at.button if b.label == 'Xác nhận').disabled)
            self.assertTrue(at.button(key='send_to_task_workflow').disabled)
            next(t for t in at.text_input if t.label.startswith('Người phụ trách cần')).set_value('Nam').run()
            self.assertFalse(next(b for b in at.button if b.label == 'Xác nhận').disabled)
            next(b for b in at.button if b.label == 'Xác nhận').click().run()
            self.assertFalse(at.exception)
            self.assertFalse(at.button(key='send_to_task_workflow').disabled)
            post.assert_not_called()
