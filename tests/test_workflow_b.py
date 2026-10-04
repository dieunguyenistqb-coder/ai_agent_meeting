import unittest
from unittest.mock import patch, Mock
from datetime import date, datetime
import requests
from streamlit.testing.v1 import AppTest
from services.n8n_service import run_workflow_b, WorkflowRunError
from services.database_service import DatabaseTaskService


class WorkflowBTests(unittest.TestCase):
    def test_post_once_no_redirect_or_retry(self):
        with patch('services.n8n_service.workflow_b_url', return_value='https://example.test/run'), patch('services.n8n_service.requests.post', return_value=Mock(status_code=200)) as post:
            run_workflow_b()
            post.assert_called_once_with('https://example.test/run', json={}, timeout=30, allow_redirects=False)

    def test_failure_and_timeout_safe(self):
        for result in (Mock(status_code=302), Mock(status_code=500), requests.Timeout('secret'), requests.ConnectionError('secret')):
            with self.subTest(result=type(result).__name__), patch('services.n8n_service.workflow_b_url', return_value='https://example.test/run'), patch('services.n8n_service.requests.post') as post:
                if isinstance(result, Exception):
                    post.side_effect = result
                else:
                    post.return_value = result
                with self.assertRaises(WorkflowRunError) as error:
                    run_workflow_b()
                self.assertNotIn('secret', str(error.exception))
                self.assertNotIn('https://', str(error.exception))
                self.assertEqual(post.call_count, 1)

    def test_missing_configuration_no_request(self):
        with patch('services.n8n_service.workflow_b_url', return_value=''), patch('services.n8n_service.requests.post') as post:
            with self.assertRaises(WorkflowRunError):
                run_workflow_b()
            post.assert_not_called()

    def test_button_runs_before_read_and_never_on_refresh(self):
        events = []
        def snapshot(**kwargs):
            events.append('read')
            return [], {}, {'today':date(2026,10,3), 'read_at':datetime(2026,10,3)}
        with patch.object(DatabaseTaskService, 'snapshot', side_effect=snapshot), patch('ui.database_tasks.workflow_b_url', return_value='https://example.test/run'), patch('ui.database_tasks.run_workflow_b', side_effect=lambda: events.append('post')):
            at = AppTest.from_string("""
from services.database_service import DatabaseTaskService
from ui.database_tasks import dashboard
dashboard(DatabaseTaskService())
""").run()
            self.assertEqual(events, ['read'])
            at.button(key='run_alert_check').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(events, ['read','post','read','read','read'])
            self.assertTrue(at.success)
            at.button(key='db_refresh').click().run()
            self.assertEqual(events, ['read','post','read','read','read','read'])

    def test_ui_missing_url_and_connection_failure(self):
        source = """
from services.database_service import DatabaseTaskService
from ui.database_tasks import dashboard
dashboard(DatabaseTaskService())
"""
        snapshot = ([], {}, {'today':date(2026,10,3), 'read_at':datetime(2026,10,3)})
        with patch.object(DatabaseTaskService, 'snapshot', return_value=snapshot), patch('ui.database_tasks.workflow_b_url', return_value=''):
            at = AppTest.from_string(source).run()
            self.assertTrue(at.button(key='run_alert_check').disabled)
        with patch.object(DatabaseTaskService, 'snapshot', return_value=snapshot), patch('ui.database_tasks.workflow_b_url', return_value='https://example.test/run'), patch('ui.database_tasks.run_workflow_b', side_effect=WorkflowRunError('Không thể kết nối hệ thống kiểm tra cảnh báo.')) as run:
            at = AppTest.from_string(source).run()
            at.button(key='run_alert_check').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(at.warning)
            self.assertFalse(at.button(key='run_alert_check').disabled)
            run.assert_called_once()

    def test_busy_flag_prevents_queuing_duplicate(self):
        from ui.database_tasks import queue_alert_check
        state = {'alert_check_busy': True}
        with patch('ui.database_tasks.st.session_state', state):
            queue_alert_check()
        self.assertNotIn('alert_check_pending', state)


if __name__ == '__main__':
    unittest.main()
