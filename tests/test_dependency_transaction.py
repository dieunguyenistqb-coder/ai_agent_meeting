"""Opt-in integration tests: real PostgreSQL SQL, isolated temporary tables only."""
import os
import unittest
from contextlib import contextmanager

from services.database_service import connect, DatabaseTaskService, DatabaseError


@unittest.skipUnless(os.environ.get('RUN_DB_TESTS') == '1', 'requires configured PostgreSQL')
class DependencyTransactionTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.addCleanup(self.conn.close)
        self.conn.execute("""CREATE TEMP TABLE tasks (
            task_id integer PRIMARY KEY, status text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now())""")
        self.conn.execute("""CREATE TEMP TABLE task_dependencies (
            task_id integer REFERENCES tasks(task_id),
            depends_on_task_id integer REFERENCES tasks(task_id),
            PRIMARY KEY (task_id, depends_on_task_id))""")
        self.conn.commit()
        self.fail_child = False
        self.service = DatabaseTaskService(self.transaction)

    @contextmanager
    def transaction(self):
        # Service opens and commits/rolls back a real transaction. Only table
        # qualification is redirected to connection-local test tables.
        test = self
        class Adapter:
            def execute(self, sql, params=None):
                if test.fail_child and "UPDATE public.tasks child" in sql:
                    raise RuntimeError('simulated child update failure')
                return test.conn.execute(sql.replace('public.', 'pg_temp.'), params)
        try:
            yield Adapter()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def seed(self, rows, dependencies):
        for key, status in rows:
            self.conn.execute('INSERT INTO pg_temp.tasks(task_id,status) VALUES (%s,%s)', (key,status))
        for child, parent in dependencies:
            self.conn.execute('INSERT INTO pg_temp.task_dependencies VALUES (%s,%s)', (child,parent))
        self.conn.commit()

    def statuses(self):
        result = {r['task_id']:r['status'] for r in
                  self.conn.execute('SELECT task_id,status FROM pg_temp.tasks').fetchall()}
        self.conn.commit()
        return result

    def test_single_parent_and_no_child(self):
        self.seed([(1,'ready'),(2,'blocked'),(3,'ready')], [(2,1)])
        self.service.update_status(1,'ready','done')
        self.assertEqual(self.statuses(), {1:'done',2:'ready',3:'ready'})
        self.service.update_status(3,'ready','done')
        self.assertEqual(self.statuses()[3], 'done')

    def test_all_parents_required_and_nonblocked_unchanged(self):
        self.seed([(1,'ready'),(2,'in_progress'),(3,'blocked'),
                   (4,'ready'),(5,'in_progress'),(6,'done')],
                  [(3,1),(3,2),(4,2),(5,2),(6,2)])
        self.service.update_status(1,'ready','done')
        self.assertEqual(self.statuses()[3], 'blocked')
        self.service.update_status(2,'in_progress','done')
        self.assertEqual(self.statuses(), {1:'done',2:'done',3:'ready',
                                          4:'ready',5:'in_progress',6:'done'})

    def test_non_done_does_not_unlock(self):
        self.seed([(1,'ready'),(2,'blocked')], [(2,1)])
        self.service.update_status(1,'ready','in_progress')
        self.assertEqual(self.statuses(), {1:'in_progress',2:'blocked'})

    def test_failure_rolls_back_parent_and_child(self):
        self.seed([(1,'ready'),(2,'blocked')], [(2,1)])
        self.fail_child = True
        with self.assertRaises(DatabaseError):
            self.service.update_status(1,'ready','done')
        self.assertEqual(self.statuses(), {1:'ready',2:'blocked'})
