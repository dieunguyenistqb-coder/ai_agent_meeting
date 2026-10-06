import unittest
from copy import deepcopy
from services.store import new_store, sync_meeting, task_key
from services.review_service import ReviewService
from ui.review_state import build_submission


class ReviewEditValidationTests(unittest.TestCase):
    def setUp(self):
        item=dict(item_id='ITEM003',content_type='task_candidate',description='Test',
            owners=[],source_excerpt=['PERSON2: Test'],commitment='explicit',
            deadline=None,deadline_status='missing',expected_decision='human_review',depends_on=[])
        self.data=dict(meeting_id='M1',items=[item,dict(item,item_id='ITEM004')])
        self.state=dict(final_object=self.data,demo_store=new_store())
        sync_meeting(self.state['demo_store'],self.data)
        self.service=ReviewService(self.state['demo_store']);self.key=task_key('M1','ITEM003')

    def test_wrong_owner_draft_retry_and_other_items(self):
        with self.assertRaisesRegex(ValueError,"Người phụ trách 'PERSON10'"):
            self.service.decide(self.key,'edit',dict(description='Test',owners=['PERSON10'],deadline=None))
        item=self.service.store['items'][self.key]
        self.assertEqual(item['review_status'],'pending')
        self.assertEqual(item['owners'],[])
        self.assertEqual(item['draft']['owners'],['PERSON10'])
        self.assertTrue(item['validation_errors'])
        self.service.decide(task_key('M1','ITEM004'),'edit',dict(description='Test',owners=['PERSON2'],deadline=None))
        with self.assertRaises(ValueError):build_submission(self.state)
        self.service.decide(self.key,'edit',dict(description='Test',owners=['PERSON2'],deadline=None))
        self.assertNotIn('validation_errors',item)
        self.assertEqual(len(build_submission(self.state)['items']),2)
        self.assertEqual(self.state['item_validation_errors'],{})

    def test_stale_invalid_confirmation_reopens_preserving_value(self):
        item=self.service.store['items'][self.key]
        item.update(owners=['PERSON10'],review_status='confirmed_by_human',expected_decision='confirmed')
        item['history'].append(dict(action='edit',changes=dict(owners=['PERSON10'])))
        with self.assertRaisesRegex(ValueError,'ITEM003'):build_submission(self.state)
        self.assertEqual(item['review_status'],'pending')
        self.assertEqual(item['draft']['owners'],['PERSON10'])
        self.assertEqual(self.state['reviewed_json']['items'][0]['expected_decision'],'human_review')
        self.assertEqual(len(self.service.pending()),2)

    def test_ui_wrong_owner_then_fix_enables_submit(self):
        import json
        from unittest.mock import patch
        from test_app import make_app, upload, navigate
        data=deepcopy(self.data);data['items']=data['items'][:1]
        for item in data['items']:item.pop('expected_decision')
        with patch('streamlit.file_uploader',return_value=upload('Ngày họp: 06-10-2026\nPERSON2: Test')), patch('src.pipeline.call_llm',return_value=json.dumps(data)), patch('services.n8n_service.requests.post') as post:
            at=make_app()
            next(b for b in at.button if b.label=='Run Extraction').click().run()
            navigate(at,'Human Review')
            next(t for t in at.text_input if t.label.startswith('Người phụ trách cần')).set_value('PERSON10').run()
            next(b for b in at.button if b.label=='Xác nhận').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(any('PERSON10' in e.value for e in at.error))
            self.assertTrue(at.button(key='send_to_task_workflow').disabled)
            at.run()
            self.assertEqual(at.session_state['demo_store']['items'][task_key('M001','ITEM003')]['draft']['owners'],['PERSON10'])
            next(t for t in at.text_input if t.label.startswith('Người phụ trách cần')).set_value('PERSON2').run()
            next(b for b in at.button if b.label=='Xác nhận').click().run()
            self.assertFalse(at.exception)
            self.assertFalse(at.button(key='send_to_task_workflow').disabled)
            post.assert_not_called()
