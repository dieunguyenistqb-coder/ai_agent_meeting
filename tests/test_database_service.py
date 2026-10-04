import unittest
from datetime import date, datetime
from unittest.mock import MagicMock

from services.database_service import (
    DatabaseTaskService, DatabaseError, parse_owner, filter_tasks,
)


class DatabaseTests(unittest.TestCase):
    def test_owner_text_formats(self):
        for raw, expected in [(None, []), ('', []), ('["PERSON1","PERSON2"]', ['PERSON1', 'PERSON2']),
                              ('PERSON1', ['PERSON1']), ('A, B', ['A, B']),
                              ('[broken', ['[broken'])]:
            self.assertEqual(parse_owner(raw), expected)

    def test_filter_multiple_meetings_and_owners(self):
        tasks = [dict(task_id=1, meeting_id='M1', item_id='ITEM001',
                      description='API', status='ready', owners=['P1', 'P2']),
                 dict(task_id=2, meeting_id='M2', item_id='ITEM001',
                      description='Test', status='blocked', owners=['P2'])]
        self.assertEqual(len(filter_tasks(tasks, owner='P2')), 2)
        self.assertEqual(filter_tasks(tasks, meeting='M2'), [tasks[1]])
        self.assertEqual(filter_tasks(tasks, search='m1'), [tasks[0]])
        self.assertEqual(filter_tasks(tasks, status='ready', owner='P2'), [tasks[0]])

    def service(self, row):
        factory = MagicMock()
        conn = factory.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = row
        return DatabaseTaskService(factory), conn, factory

    def test_allowed_updates_parameterized_and_guarded(self):
        for before, after in [('ready', 'in_progress'), ('ready', 'done'), ('in_progress', 'done')]:
            service, conn, _ = self.service({'task_id': 9})
            service.update_status(9, before, after)
            sql, params = conn.execute.call_args_list[1].args
            self.assertIn('AND status = %s', sql)
            self.assertIn('updated_at = NOW()', sql)
            self.assertEqual(params, (after, 9, before))

    def test_blocked_review_and_terminal_cannot_change(self):
        for before in ('blocked', 'done', 'confirmed', 'pending_review', 'editing', 'rejected'):
            service, _, factory = self.service(None)
            with self.assertRaises(DatabaseError):
                service.update_status(1, before, 'in_progress')
            factory.assert_not_called()

    def test_stale_update(self):
        service, _, _ = self.service(None)
        with self.assertRaisesRegex(DatabaseError, 'đã đổi trạng thái'):
            service.update_status(1, 'ready', 'done')

    def test_error_does_not_expose_credentials(self):
        service = DatabaseTaskService(MagicMock(side_effect=RuntimeError('secret-password')))
        with self.assertRaises(DatabaseError) as error:
            service.snapshot()
        self.assertNotIn('secret-password', str(error.exception))


class DatabaseDashboardTests(unittest.TestCase):
    def test_dashboard_reads_db_and_updates_then_reloads(self):
        from streamlit.testing.v1 import AppTest
        source = """
import streamlit as st
from datetime import date, datetime
from ui.database_tasks import dashboard
class Service:
    def snapshot(self, include_clock=False):
        return [dict(task_id=7, meeting_id='M2', item_id='ITEM001',
            description='Database task', owner='["P1","P2"]', owners=['P1','P2'],
            deadline=None, status=st.session_state.get('test_status', 'ready'),
            updated_at='2026-10-03')], {'P2': 'Name Two'}, {'today': date(2026,10,3), 'read_at': datetime(2026,10,3)}
    def update_status(self, key, before, after):
        st.session_state.test_status = after
dashboard(Service())
"""
        at = AppTest.from_string(source).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.metric[0].value, '1')
        self.assertIn('Name Two', at.get('html')[0].proto.body)
        next(b for b in at.button if b.label == 'Lưu trạng thái').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['test_status'], 'in_progress')
        self.assertEqual(at.metric[0].value, '1')
        next(b for b in at.button if b.label == 'Lưu trạng thái').click().run()
        self.assertEqual(at.session_state['test_status'], 'done')
        self.assertEqual(at.metric[3].value, '0')
        self.assertFalse(any(b.label == 'Lưu trạng thái' for b in at.button))

class DependencyTests(unittest.TestCase):
    def prerequisite(self, task_id=1, status='in_progress', deadline=None):
        return dict(task_id=task_id, meeting_id='M066', item_id=f'ITEM{task_id:03}',
                    description='Audit <script>', owner='["PERSON2"]', owners=['PERSON2'],
                    deadline=deadline, status=status)

    def test_batch_query_and_owner_parsing(self):
        factory = MagicMock()
        conn = factory.return_value.__enter__.return_value
        task = dict(task_id=3, owner=None)
        deps = [dict(self.prerequisite(), dependent_task_id=3),
                dict(self.prerequisite(2), dependent_task_id=3)]
        conn.execute.return_value.fetchall.side_effect = [
            [task, dict(task_id=4, owner='PERSON2')], deps,
            [dict(person_id='PERSON2', name='Trần Thị Bé')]]
        tasks, employees = DatabaseTaskService(factory).snapshot()
        self.assertEqual(conn.execute.call_count, 3)
        self.assertIn('JOIN public.tasks p ON p.task_id = d.depends_on_task_id',
                      conn.execute.call_args_list[1].args[0])
        self.assertEqual(len(tasks[0]['dependencies']), 2)
        self.assertEqual(tasks[0]['dependencies'][0]['owners'], ['PERSON2'])
        self.assertEqual(tasks[1]['dependencies'], [])
        self.assertEqual(employees['PERSON2'], 'Trần Thị Bé')

    def test_summaries_and_html(self):
        from ui.database_tasks import dependency_summary, task_table
        task = dict(self.prerequisite(3), status='ready', dependencies=[])
        self.assertEqual(dependency_summary(task), '')
        task.update(status='blocked', dependencies=[self.prerequisite()])
        self.assertEqual(dependency_summary(task), '↳ bởi M066 · ITEM001')
        task['dependencies'].append(self.prerequisite(2))
        self.assertEqual(dependency_summary(task), '↳ bởi M066 · ITEM001 +1')
        html = task_table([task], lambda t: 'PERSON2')
        self.assertEqual(html.count('<th scope='), 6)
        self.assertIn('<small title=', html)
        self.assertNotIn('<script>', html)
        self.assertIn('Audit &lt;script&gt;', html)
        task['status'] = 'ready'
        self.assertEqual(dependency_summary(task), '')
        task['status'] = 'blocked'
        task['dependencies'][0]['status'] = 'done'
        self.assertEqual(dependency_summary(task), '↳ bởi M066 · ITEM002')

    def test_overdue_boundaries(self):
        from datetime import date, timedelta
        from ui.database_tasks import prerequisite_overdue, deadline_text
        today = date(2026, 10, 3)
        self.assertTrue(prerequisite_overdue(self.prerequisite(deadline=today-timedelta(days=1)), today))
        for deadline in (None, today, today+timedelta(days=1)):
            self.assertFalse(prerequisite_overdue(self.prerequisite(deadline=deadline), today))
        self.assertFalse(prerequisite_overdue(self.prerequisite(status='done', deadline=today-timedelta(days=1)), today))
        self.assertEqual(deadline_text(None), 'Chưa xác định')

    def test_details_all_dependencies_and_no_ui_unblock(self):
        from streamlit.testing.v1 import AppTest
        from datetime import date
        from unittest.mock import patch
        task = dict(self.prerequisite(3), status='blocked', updated_at=None,
                    dependencies=[self.prerequisite(deadline=date(2000, 1, 1)),
                                  self.prerequisite(2, status='done')])
        source = """
from services.database_service import DatabaseTaskService
from ui.database_tasks import dashboard
dashboard(DatabaseTaskService())
"""
        with patch.object(DatabaseTaskService, 'snapshot', return_value=([task], {'PERSON2':'Trần Thị Bé'}, {'today':date(2026,10,3), 'read_at':datetime(2026,10,3)})), patch.object(DatabaseTaskService, 'update_status') as update:
            at = AppTest.from_string(source).run()
            self.assertFalse(at.exception)
            self.assertTrue(any('Công việc tiền đề' in m.value for m in at.markdown))
            self.assertEqual(len(at.warning), 1)
            self.assertEqual(at.warning[0].value, 'Công việc tiền đề đã quá hạn')
            self.assertEqual(at.warning[0].proto.icon, '⚠️')
            self.assertTrue(any('M066 · ITEM002' in t.value for t in at.text))
            self.assertTrue(any('PERSON2 · Trần Thị Bé' in t.value for t in at.text))
            self.assertFalse(any(b.label == 'Lưu trạng thái' for b in at.button))
            for dep in task['dependencies']:
                dep['status'] = 'done'
            at.run()
            self.assertFalse(at.warning)
            self.assertIn('Bị chặn', at.get('html')[0].proto.body)
            update.assert_not_called()
            self.assertFalse(any('Workflow' in i.value for i in at.info))
            task['dependencies'] = []
            at.run()
            self.assertTrue(any('Không có công việc tiền đề' in c.value for c in at.caption))
            self.assertNotIn('↳ bởi', at.get('html')[0].proto.body)


if __name__ == '__main__':
    unittest.main()
