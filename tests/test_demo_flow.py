"""Session flow tests: all provider calls are mocked."""
from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch
from src import pipeline
from ui.demo import load_demo, reset_session, refresh_views
from services.review_service import ReviewService
from services.task_service import TaskService
from services.monitoring_service import MonitoringService
from services.store import task_key
from test_app import make_app, navigate, upload, response


class DemoFlowTests(unittest.TestCase):
    def test_demo_review_status_and_isolation(self):
        state = {'authenticated': True, 'extraction_count': 4}
        load_demo(state)
        original = deepcopy(state['final_object'])
        reviews = ReviewService(state['demo_store'])
        tasks = TaskService(state['demo_store'])
        key = task_key('DEMO', 'ITEM002')
        reviews.decide(key, 'edit', dict(description='Mô tả đã sửa', owners=['Nhân vật C'], deadline=None))
        tasks.update_status(key, 'completed')
        refresh_views(state)
        self.assertEqual(len(state['tasks']), 3)
        self.assertEqual(len(state['reviewed_items']), 1)
        self.assertEqual(state['final_object'], original)
        refresh_views(state)
        self.assertEqual(len(state['tasks']), 3)
        reset_session(state)
        self.assertTrue(state['authenticated'])
        self.assertEqual(state['extraction_count'], 4)
        self.assertNotIn('final_object', state)
        self.assertNotIn('tasks', state)

    def test_alerts_missing_deadline_and_rejection(self):
        state = {}
        load_demo(state)
        reviews = ReviewService(state['demo_store'])
        tasks = TaskService(state['demo_store'])
        reviews.decide(task_key('DEMO', 'ITEM002'), 'reject')
        self.assertEqual(len(tasks.list_tasks()), 2)
        for task in state['demo_store']['items'].values():
            task.update(deadline=None, owners=[], status='not_started')
        alerts = MonitoringService(tasks, reviews).alerts(date(2030, 1, 1))
        self.assertNotIn('task overdue', [a['type'] for a in alerts])
        self.assertIn('unassigned', [a['type'] for a in alerts])
        self.assertIn('missing deadline', [a['type'] for a in alerts])

    def test_all_pages_demo_reset_and_no_api(self):
        with patch.object(pipeline, 'call_llm') as llm:
            at = make_app()
            self.assertFalse(any('Ask' in b.label for b in at.button))
            next(b for b in at.button if b.label == 'Tải dữ liệu demo').click().run()
            self.assertFalse(at.exception)
            original = deepcopy(at.session_state['final_object'])
            for screen in ('Extraction Result', 'Validation & JSON', 'Human Review', 'Task Dashboard', 'Monitoring & Alerts', 'Transcript'):
                navigate(at, screen)
                self.assertFalse(at.exception, screen)
                self.assertEqual(at.session_state['final_object'], original)
            self.assertTrue(next(b for b in at.button if b.label == 'Đặt lại phiên demo').disabled)
            at.checkbox(key='confirm_reset').check().run()
            next(b for b in at.button if b.label == 'Đặt lại phiên demo').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(at.session_state['authenticated'])
            self.assertIsNone(at.session_state['final_object'])
            self.assertFalse(at.session_state['tasks'])
            llm.assert_not_called()

    def test_demo_replaced_by_upload(self):
        with patch.object(pipeline, 'call_llm', side_effect=response) as llm:
            at = make_app()
            next(b for b in at.button if b.label == 'Tải dữ liệu demo').click().run()
            with patch('streamlit.file_uploader', return_value=upload()):
                at.run()
                self.assertFalse(at.session_state['tasks'])
                next(b for b in at.button if b.label == 'Run Extraction').click().run()
                self.assertFalse(at.exception)
                self.assertEqual({t['meeting_id'] for t in at.session_state['tasks']}, {'M001'})
                self.assertEqual(llm.call_count, 1)

    def test_ui_review_reject_and_status(self):
        with patch.object(pipeline, 'call_llm') as llm:
            at = make_app()
            next(b for b in at.button if b.label == 'Tải dữ liệu demo').click().run()
            navigate(at, 'Human Review')
            next(b for b in at.button if b.label == 'Từ chối').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.session_state['tasks']), 2)
            navigate(at, 'Task Dashboard')
            next(b for b in at.button if b.label == 'View').click().run()
            next(s for s in at.selectbox if s.label == 'Cập nhật trạng thái').select('completed')
            next(b for b in at.button if b.label == 'Cập nhật trạng thái').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['tasks'][0]['status'], 'completed')
            llm.assert_not_called()
