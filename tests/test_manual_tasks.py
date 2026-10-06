from copy import deepcopy
import unittest
from services.store import new_store, sync_meeting, task_key
from services.review_service import ReviewService
from ui.review_state import build_submission


class ManualTasksTests(unittest.TestCase):
    def setUp(self):
        self.original = dict(meeting_id='MTEST', meeting_date='2026-10-05',
                            meeting_date_evidence=None, items=[])
        self.state = dict(final_object=deepcopy(self.original), demo_store=new_store())
        sync_meeting(self.state['demo_store'], self.original)
        self.service = ReviewService(self.state['demo_store'])

    def add(self, **changes):
        return self.service.save_added('MTEST', dict(description='Công việc giả lập',
            owners=['PERSON1'], **changes))

    def test_add_dates_dependency_edit_remove_and_rebuild(self):
        self.assertEqual(build_submission(self.state)['items'], [])
        a = self.add()
        b = self.add(deadline='2026-10-10', depends_on=[a])
        result = build_submission(self.state)
        self.assertEqual(result, build_submission(self.state))
        self.assertEqual(result['items'][0]['deadline_status'], 'missing')
        self.assertIsNone(result['items'][0]['deadline'])
        self.assertIsNone(result['items'][0]['deadline_text'])
        self.assertEqual(result['items'][1]['deadline_status'], 'resolved')
        self.assertEqual(result['items'][1]['depends_on'], [a])
        self.assertNotIn('item_origin', result['items'][0])
        self.service.save_added('MTEST', dict(description='Đã sửa', owners=['PERSON2']), b)
        self.assertEqual(build_submission(self.state)['items'][1]['description'], 'Đã sửa')
        self.service.discard_added(task_key('MTEST', b))
        self.assertEqual(len(build_submission(self.state)['items']), 1)
        self.assertEqual(self.add(), 'ITEM003')
        sync_meeting(self.state['demo_store'], self.original)
        self.assertEqual(len(build_submission(self.state)['items']), 2)
        self.assertEqual(self.state['final_object'], self.original)

    def test_invalid_dependencies_and_required_fields(self):
        for changes in [dict(description='', owners=['P']), dict(description='X', owners=[]),
                        dict(description='X', owners=['P'], depends_on=['ITEM001']),
                        dict(description='X', owners=['P'], depends_on=['ITEM099'])]:
            with self.assertRaises(ValueError): self.service.save_added('MTEST', changes)
        a = self.add()
        self.add(depends_on=[a])
        self.service.discard_added(task_key('MTEST', a))
        with self.assertRaisesRegex(ValueError, 'ITEM002'): build_submission(self.state)

    def test_new_extraction_clears_additions(self):
        self.add()
        updated = deepcopy(self.original)
        updated['meeting_date'] = '2026-10-06'
        sync_meeting(self.state['demo_store'], updated)
        self.state['final_object'] = updated
        self.assertEqual(build_submission(self.state)['items'], [])

    def test_extraction_grounding_still_required(self):
        from src.schema_validator import validate_business_rules
        from src.schemas import FinalMeetingOutput
        self.add()
        final = FinalMeetingOutput.model_validate(build_submission(self.state))
        with self.assertRaisesRegex(ValueError, 'owner_grounding'): validate_business_rules(final)

    def test_ui_add_rerun_and_single_combined_submission(self):
        from unittest.mock import patch
        from test_app import make_app, upload, response, navigate
        with patch('streamlit.file_uploader', return_value=upload()), patch('src.pipeline.call_llm', side_effect=response), patch('services.n8n_service.requests.post') as post:
            post.return_value.status_code = 200
            at = make_app()
            next(b for b in at.button if b.label == 'Run Extraction').click().run()
            navigate(at, 'Human Review')
            self.assertFalse(any(b.label == 'Thêm công việc' for b in at.button))
            at.button(key='review_add_missing_task').click().run()
            self.assertTrue(at.session_state['open_add_missing_task_form'])
            next(b for b in at.button if b.label == 'Hủy').click().run()
            self.assertFalse(at.session_state['open_add_missing_task_form'])
            self.assertEqual(len(at.session_state['demo_store']['items']), 1)
            self.assertFalse(any(b.label == 'Thêm công việc' for b in at.button))
            navigate(at, 'Extraction Result')
            at.button(key='add_missing_task').click().run()
            self.assertTrue(at.session_state['open_add_missing_task_form'])
            next(t for t in at.text_area if t.label == 'Nội dung công việc *').set_value('Task bổ sung giả lập')
            next(t for t in at.text_input if t.label.startswith('Người phụ trách *')).set_value('PERSON2')
            next(b for b in at.button if b.label == 'Thêm công việc').click().run()
            self.assertFalse(at.exception)
            self.assertFalse(at.session_state['open_add_missing_task_form'])
            self.assertTrue(any('Người dùng bổ sung' in e.label for e in at.expander))
            at.run()
            self.assertEqual(len(at.session_state['demo_store']['items']), 2)
            post.assert_not_called()
            self.assertFalse(at.button(key='send_to_task_workflow').disabled)
            at.button(key='send_to_task_workflow').click().run()
            self.assertFalse(at.exception)
            post.assert_called_once()
            items = post.call_args.kwargs['json']['items']
            self.assertEqual([i['item_id'] for i in items], ['ITEM001', 'ITEM002'])
            self.assertEqual(items[1]['owners'], ['PERSON2'])

    def test_six_qwen_items_navigation_and_one_explicit_add(self):
        import json
        from unittest.mock import patch, Mock
        from test_app import make_app, upload, response, navigate
        from ui.review_state import rebuild_final_json
        base = json.loads(response(dict(meeting_id='M001', meeting_date=None, meeting_date_evidence=None)))['items'][0]
        items = [dict(deepcopy(base), item_id=f'ITEM{i:03d}', description=f'Công việc giả lập {i}') for i in range(1, 7)]
        result = Mock(status_code=200, json=lambda:dict(ok=True, model_version='v6', prompt_version='prompt_v6', items=items))
        with patch('streamlit.file_uploader', return_value=upload()), patch('services.extraction_service.requests.post', return_value=result) as post:
            at = make_app()
            at.radio(key='extraction_provider').set_value('qwen_v6').run()
            next(b for b in at.button if b.label == 'Run Extraction').click().run()
            for page in ['Human Review', 'Extraction Result', 'Human Review']:
                navigate(at, page)
                at.run()
                self.assertFalse(at.exception)
                self.assertEqual(len(at.session_state['demo_store']['items']), 6)
                self.assertEqual(len(json.loads(at.session_state['raw_output'])['items']), 6)
            before = deepcopy(at.session_state['demo_store'])
            original = deepcopy(at.session_state['final_json'])
            for _ in range(3):
                rebuilt, _ = rebuild_final_json(original, before['items'])
                self.assertEqual(len(rebuilt['items']), 6)
            self.assertEqual(before, at.session_state['demo_store'])
            at.button(key='review_add_missing_task').click().run()
            next(t for t in at.text_area if t.label == 'Nội dung công việc *').set_value('Bổ sung giả lập')
            next(t for t in at.text_input if t.label.startswith('Người phụ trách *')).set_value('PERSON2')
            next(b for b in at.button if b.label == 'Thêm công việc').click().run()
            for _ in range(3):
                at.run()
                self.assertEqual(len(at.session_state['demo_store']['items']), 7)
                self.assertEqual(len(at.session_state['reviewed_json']['items']), 7)
                self.assertEqual(len(json.loads(at.session_state['raw_output'])['items']), 6)
            post.assert_called_once()
            navigate(at, 'Transcript')
            next(b for b in at.button if b.label == 'Run Extraction').click().run()
            self.assertEqual(len(at.session_state['demo_store']['items']), 6)
