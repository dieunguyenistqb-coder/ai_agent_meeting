from copy import deepcopy
from datetime import date, datetime
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import config
from services.store import new_store, sync_meeting, task_key
from services.review_service import ReviewService
from services.task_service import TaskService
from services.monitoring_service import MonitoringService
from test_app import upload, response, navigate, APP, make_app
from src import pipeline


def sample(mid='M001'):
    return dict(meeting_id=mid, items=[dict(item_id='ITEM001', description='API', owners=['Nam'],
        deadline='2026-09-01', deadline_status='resolved', source_excerpt=['Nam và Lan: làm API'], content_type='task_candidate',
        commitment='tentative', expected_decision='human_review', review_reason='Chờ xác nhận', depends_on=[])])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        for name in ('ENABLE_HUMAN_REVIEW', 'ENABLE_TASK_DASHBOARD', 'ENABLE_MONITORING'):
            toggle = patch.object(config, name, True)
            toggle.start()
            self.addCleanup(toggle.stop)
        self.store = new_store()
        self.data = sample()
        sync_meeting(self.store, self.data)
        self.reviews = ReviewService(self.store)
        self.tasks = TaskService(self.store)
        self.key = task_key('M001', 'ITEM001')

    def test_review_edit_and_snapshot_isolation(self):
        original = deepcopy(self.data)
        self.reviews.decide(self.key, 'edit', dict(description='Edited', owners=['Lan'], deadline=None))
        self.assertEqual(self.tasks.get(self.key)['owners'], ['Lan'])
        self.assertEqual(self.data, original)
        self.assertEqual(len(self.reviews.pending()), 0)
        self.assertEqual(self.reviews.reviewed_today(), 1)
        sync_meeting(self.store, self.data)
        self.assertEqual(self.tasks.get(self.key)['description'], 'Edited')
        with self.assertRaises(ValueError):
            self.reviews.decide(self.key, 'confirm')

    def test_reject_and_multi_meeting(self):
        sync_meeting(self.store, sample('M002'))
        self.reviews.decide(self.key, 'reject')
        self.assertFalse(self.tasks.list_tasks())
        self.assertEqual(len(self.reviews.pending()), 1)
        self.assertEqual(len(self.store['items']), 2)

    def test_status_filters_alerts(self):
        self.reviews.decide(self.key, 'confirm')
        self.assertEqual(len(self.tasks.list_tasks(owner='Nam', meeting='M001', search='api')), 1)
        self.assertFalse(self.tasks.list_tasks(owner='Lan'))
        monitor = MonitoringService(self.tasks, self.reviews)
        self.assertEqual(monitor.alerts(date(2026, 9, 2))[0]['type'], 'task overdue')
        self.assertEqual(monitor.alerts(date(2026, 8, 30))[0]['type'], 'task due soon')
        self.tasks.update_status(self.key, 'blocked')
        self.assertEqual([a['type'] for a in monitor.alerts(date(2026, 9, 2))], ['blocked task'])
        self.tasks.update_status(self.key, 'done')
        self.assertFalse(monitor.alerts(date(2026, 9, 2)))
        with self.assertRaises(ValueError):
            self.tasks.update_status(self.key, 'on_hold')
        self.assertEqual(len(self.tasks.get(self.key)['history']), 4)

    def test_feature_flags(self):
        with patch.object(config, 'ENABLE_HUMAN_REVIEW', False), patch.object(config, 'ENABLE_TASK_DASHBOARD', False), patch.object(config, 'ENABLE_MONITORING', False), patch.object(pipeline, 'call_llm') as llm:
            at = make_app()
            self.assertEqual([button.label for button in at.button[1:4]],
                             ['Transcript', 'Kết quả trích xuất', 'Kiểm tra JSON'])
            llm.assert_not_called()

    def test_dashboard_detail_and_monitoring_navigation(self):
        with patch('services.database_service.DatabaseTaskService.snapshot', side_effect=lambda include_clock=False: ([], {}, {'today': date(2026, 10, 3), 'read_at': datetime(2026, 10, 3)}) if include_clock else ([], {})), patch('streamlit.file_uploader', return_value=upload()), patch.object(pipeline, 'call_llm', side_effect=response) as llm:
            at = make_app()
            at.button[0].click().run()
            navigate(at, 'Task Dashboard')
            self.assertFalse(at.exception)
            self.assertEqual(at.metric[0].value, '0')  # Extraction is not a DB task.
            self.assertFalse(any(b.key == 'nav_Monitoring & Alerts' for b in at.button))
            self.assertTrue(any(b.label == 'Theo dõi công việc & cảnh báo' for b in at.button))
            self.assertFalse(at.exception)
            navigate(at, 'Human Review')
            self.assertFalse(at.exception)
            self.assertEqual(llm.call_count, 1)

    def test_review_ui_confirm(self):
        def review_response(payload):
            import json
            data = json.loads(response(payload))
            data['items'][0]['commitment'] = 'tentative'
            return json.dumps(data)
        with patch('services.database_service.DatabaseTaskService.snapshot', side_effect=lambda include_clock=False: ([], {}, {'today': date(2026, 10, 3), 'read_at': datetime(2026, 10, 3)}) if include_clock else ([], {})), patch('streamlit.file_uploader', return_value=upload()), patch.object(pipeline, 'call_llm', side_effect=review_response):
            at = make_app()
            at.button[0].click().run()
            navigate(at, 'Human Review')
            self.assertFalse(at.exception)
            next(b for b in at.button if b.label == 'Xác nhận').click().run()
            self.assertFalse(at.exception)
            navigate(at, 'Task Dashboard')
            self.assertEqual(at.metric[0].value, '0')  # Review alone does not persist to DB.
            self.assertEqual(at.session_state['final_object'].items[0].expected_decision, 'human_review')
