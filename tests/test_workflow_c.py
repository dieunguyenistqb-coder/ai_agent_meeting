import unittest
from unittest.mock import patch, Mock
import requests
from services.n8n_service import run_workflow_c_reminder, WorkflowRunError, REMINDER_STATUSES
from streamlit.testing.v1 import AppTest


class ReminderTests(unittest.TestCase):
    def test_all_statuses_and_payload(self):
        for status in REMINDER_STATUSES:
            with self.subTest(status=status), patch('services.n8n_service.requests.post', return_value=Mock(status_code=200, json=lambda: {'status': status})) as post:
                self.assertEqual(run_workflow_c_reminder(3), status)
                self.assertEqual(post.call_args.kwargs, dict(json={'task_id':3}, timeout=30, allow_redirects=False))

    def test_invalid_id_no_post(self):
        with patch('services.n8n_service.requests.post') as post:
            for value in (None, '3', True, 0, -1):
                self.assertEqual(run_workflow_c_reminder(value), 'invalid_task_id')
            post.assert_not_called()

    def test_transport_and_invalid_response(self):
        for error in (requests.Timeout('secret'), requests.ConnectionError('secret')):
            with patch('services.n8n_service.requests.post', side_effect=error):
                with self.assertRaises(WorkflowRunError) as result:
                    run_workflow_c_reminder(3)
                self.assertNotIn('secret', str(result.exception))
        for code, data in ((500, {'status':'sent'}), (200, {}), (200, []), (200, {'status':['sent']})):
            with patch('services.n8n_service.requests.post', return_value=Mock(status_code=code, json=lambda:data)):
                with self.assertRaises(WorkflowRunError):
                    run_workflow_c_reminder(3)

    def test_ui_once_and_refresh_after_sent(self):
        source = """
import streamlit as st
from datetime import datetime, date
from ui.database_tasks import dashboard
class Service:
    def snapshot(self, **kwargs):
        st.session_state.reads = st.session_state.get('reads', 0) + 1
        return [dict(task_id=3, meeting_id='M1',item_id='ITEM003',description='Task',
          status='ready',owners=[],deadline=None,updated_at=None,dependencies=[],
          last_reminded_at=datetime(2026,10,4) if st.session_state.get('sent') else None)], {}, dict(today=date(2026,10,4),read_at=datetime(2026,10,4))
dashboard(Service())
"""
        def send(task_id):
            import streamlit as st
            self.assertEqual(st.session_state.reminder_busy, 3)
            st.session_state.sent = True
            return 'sent'
        with patch('ui.task_reminders.run_workflow_c_reminder', side_effect=send) as post:
            at = AppTest.from_string(source).run()
            post.assert_not_called()
            at.button(key='remind_3').click().run()
            self.assertFalse(at.exception)
            post.assert_called_once_with(3)
            self.assertTrue(any('Đã gửi nhắc nhở' in x.value for x in at.success))
            self.assertTrue(any('Lần nhắc gần nhất:' in x.value for x in at.caption))
            self.assertFalse(at.button(key='remind_3').disabled)
            at.button(key='db_refresh').click().run()
            post.assert_called_once()
