from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch

from services.database_service import DatabaseTaskService, DatabaseError
from services.monitoring_service import attention_tasks
from streamlit.testing.v1 import AppTest

TODAY = date(2026, 10, 3)
CLOCK = {'today': TODAY, 'read_at': datetime(2026, 10, 3, 15, 30, tzinfo=timezone.utc)}


def task(key, status, days=None):
    return dict(task_id=key, meeting_id='M066', item_id=f'ITEM{key:03}',
                description=f'Task {key}', owners=['PERSON2'], owner='["PERSON2"]',
                status=status, deadline=TODAY + timedelta(days=days) if days is not None else None,
                dependencies=[], updated_at=None)


class MonitoringTests(unittest.TestCase):
    def test_groups_and_boundaries(self):
        rows = [task(1, 'in_progress', -1), task(2, 'ready', 0),
                task(3, 'ready', 3), task(4, 'ready', 4),
                task(5, 'blocked', -2), task(6, 'done', -1),
                task(7, 'done', 1), task(8, 'pending_review', -1),
                task(9, 'editing', 1), task(10, 'confirmed', -1),
                task(11, 'rejected', -1), task(12, 'ready')]
        groups = {t['task_id']: t['alert_groups'] for t in attention_tasks(rows, TODAY)}
        self.assertEqual(groups, {1:['overdue'], 2:['due_soon'], 3:['due_soon'],
                                 5:['overdue','blocked']})

    def test_clock_is_read_from_database(self):
        factory = MagicMock()
        conn = factory.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = CLOCK
        conn.execute.return_value.fetchall.side_effect = [[], [], []]
        self.assertEqual(DatabaseTaskService(factory).snapshot(include_clock=True),
                         ([], {}, CLOCK))
        self.assertIn('CURRENT_DATE', conn.execute.call_args_list[0].args[0])
        self.assertEqual(conn.execute.call_count, 4)

    def test_ui_read_only_filters_blocker_and_refresh(self):
        rows = [task(1, 'in_progress', -1), task(2, 'ready', 3),
                task(3, 'blocked'), task(4, 'pending_review', -4), task(5,'done',-1)]
        rows[2]['dependencies'] = [task(6, 'in_progress', -1), task(7,'done',-1)]
        source = """
from services.database_service import DatabaseTaskService
from ui.database_tasks import dashboard
dashboard(DatabaseTaskService())
"""
        with patch.object(DatabaseTaskService, 'snapshot', return_value=(rows, {'PERSON2':'Trần Thị Bé'}, CLOCK)) as read, patch.object(DatabaseTaskService,'update_status') as write:
            at = AppTest.from_string(source).run()
            self.assertFalse(at.exception)
            self.assertEqual([m.label for m in at.metric],
                             ['Tổng số task','Sắp đến hạn','Quá hạn','Bị chặn'])
            self.assertEqual([m.value for m in at.metric], ['4','1','1','1'])
            self.assertEqual(len(at.warning), 1)
            self.assertTrue(any('ITEM006' in t.value for t in at.text))
            self.assertTrue(any('ITEM007' in t.value for t in at.text))
            self.assertTrue(any('PERSON2 · Trần Thị Bé' in t.value for t in at.text))
            self.assertIn('ITEM005', at.get('html')[0].proto.body)
            self.assertFalse(any(b.label == 'Xác nhận' for b in at.button))
            at.selectbox(key='db_alert_group').select('overdue').run()
            self.assertNotIn('ITEM004', at.get('html')[0].proto.body)
            self.assertIn('ITEM001', at.get('html')[0].proto.body)
            self.assertFalse(any('Human Review' in m.value for m in at.markdown))
            self.assertFalse(any('Human Review' in c.value for c in at.caption))
            rows.clear()
            at.button[0].click().run()
            self.assertEqual([m.value for m in at.metric], ['0']*4)
            read.assert_called_with(include_clock=True)
            write.assert_not_called()

    def test_database_error_has_no_demo_fallback(self):
        with patch.object(DatabaseTaskService,'snapshot', side_effect=DatabaseError('PostgreSQL')):
            at = AppTest.from_string("""
from services.database_service import DatabaseTaskService
from ui.database_tasks import dashboard
dashboard(DatabaseTaskService())
""").run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.error), 1)
            self.assertFalse(at.metric)
            self.assertNotIn('PostgreSQL', at.error[0].value)


if __name__ == '__main__':
    unittest.main()
