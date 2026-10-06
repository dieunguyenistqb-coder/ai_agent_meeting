from copy import deepcopy
import unittest
from unittest.mock import patch
from services.store import new_store, sync_meeting, task_key
from services.review_service import ReviewService
from ui.review_state import build_submission
from test_app import response, make_app, upload, navigate
import json


class SubmissionTests(unittest.TestCase):
    def state(self):
        data=json.loads(response(dict(meeting_id='M1',meeting_date=None,meeting_date_evidence=None)))
        for item in data['items']:
            item.update(expected_decision='human_review', review_reason='Review', commitment='tentative')
        state={'final_object':data,'demo_store':new_store()}
        sync_meeting(state['demo_store'],data)
        return state

    def test_pending_then_confirm_preserves_semantics(self):
        state=self.state()
        with self.assertRaises(ValueError): build_submission(state)
        for key in list(state['demo_store']['items']):
            ReviewService(state['demo_store']).decide(key,'confirm')
            self.assertEqual(state['demo_store']['items'][key]['review_status'],'confirmed_by_human')
        result=build_submission(state)
        self.assertEqual(result['items'][0]['commitment'],'tentative')
        self.assertEqual(result['items'][0]['expected_decision'],'confirmed')
        self.assertNotIn('review_status',result['items'][0])

    def test_duplicate_and_dropped_dependency_block(self):
        state=self.state()
        base=state['final_object']['items'][0]
        second=deepcopy(base);second['item_id']='ITEM002';second['depends_on']=[base['item_id']]
        state['final_object']['items'].append(second)
        sync_meeting(state['demo_store'],state['final_object'])
        service=ReviewService(state['demo_store'])
        keys=list(state['demo_store']['items'])
        service.decide(keys[0],'reject')
        with self.assertRaisesRegex(ValueError,'dependency_exists'):service.decide(keys[1],'confirm')
        with self.assertRaises(ValueError):build_submission(state)
        state=self.state()
        state['final_object']['items'].append(deepcopy(state['final_object']['items'][0]))
        sync_meeting(state['demo_store'],state['final_object'])
        for key in state['demo_store']['items']:ReviewService(state['demo_store']).decide(key,'confirm')
        with self.assertRaisesRegex(ValueError,'trùng'):build_submission(state)

    def test_ui_review_gate_and_explicit_submit(self):
        def review_response(payload):
            data=json.loads(response(payload))
            data['items'][0]['commitment']='tentative'
            return json.dumps(data)
        with patch('streamlit.file_uploader',return_value=upload()), patch('src.pipeline.call_llm',side_effect=review_response), patch('services.n8n_service.requests.post') as post:
            post.return_value.status_code=200
            at=make_app()
            next(b for b in at.button if b.label=='Run Extraction').click().run()
            navigate(at,'Extraction Result')
            self.assertFalse(any(b.key=='send_to_task_workflow' for b in at.button))
            at.button(key='continue_review').click().run()
            self.assertTrue(at.button(key='send_to_task_workflow').disabled)
            next(b for b in at.button if b.label=='Xác nhận').click().run()
            self.assertFalse(at.button(key='send_to_task_workflow').disabled)
            post.assert_not_called()
            at.button(key='send_to_task_workflow').click().run()
            self.assertFalse(at.exception)
            post.assert_called_once()
            self.assertEqual(post.call_args.kwargs['json']['items'][0]['commitment'],'tentative')
