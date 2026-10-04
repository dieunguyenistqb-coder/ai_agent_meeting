"""Direct PostgreSQL task access; independent of extraction and demo state."""
import json
import os
from pathlib import Path

from dotenv import dotenv_values

TRANSITIONS = {'ready': ('in_progress', 'done'), 'in_progress': ('done',)}


class DatabaseError(ValueError):
    """Safe message suitable for display without credentials."""


def parse_owner(value):
    if value is None or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except ValueError:
        return [value]
    if isinstance(parsed, list) and all(isinstance(v, str) for v in parsed):
        return parsed
    if isinstance(parsed, str):
        return [parsed] if parsed else []
    return [value]


def connection_settings():
    local = dotenv_values(Path(__file__).resolve().parents[1] / '.env')
    values = {key: os.environ.get(key, local.get(key)) for key in
              ('DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_SSLMODE')}
    missing = [key for key in ('DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD') if not values[key]]
    if missing:
        raise DatabaseError('Thiếu cấu hình PostgreSQL: ' + ', '.join(missing))
    try:
        port = int(values['DB_PORT'] or 5432)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise DatabaseError('DB_PORT phải là số nguyên từ 1 đến 65535.') from None
    return dict(host=values['DB_HOST'], port=port, dbname=values['DB_NAME'],
                user=values['DB_USER'], password=values['DB_PASSWORD'],
                sslmode=values['DB_SSLMODE'] or 'prefer', connect_timeout=5,
                options='-c statement_timeout=10000')


def connect():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        raise DatabaseError('Thiếu driver PostgreSQL. Chạy pip install -r requirements.txt.') from None
    return psycopg.connect(**connection_settings(), row_factory=dict_row)


class DatabaseTaskService:
    def __init__(self, connection_factory=connect):
        self.connection_factory = connection_factory

    def snapshot(self, include_clock=False):
        """One short-lived connection per refresh, shared by both reads and closed."""
        try:
            with self.connection_factory() as conn:
                if include_clock:
                    clock = conn.execute(
                        'SELECT CURRENT_DATE AS today, CURRENT_TIMESTAMP AS read_at'
                    ).fetchone()
                tasks = conn.execute("""
                    SELECT t.task_id, t.meeting_id, t.item_id, t.task AS description,
                           t.owner, t.deadline, t.status, t.updated_at, t.last_reminded_at,
                           m.title AS meeting_title
                    FROM public.tasks t
                    LEFT JOIN public.meetings m ON m.meeting_id = t.meeting_id
                    ORDER BY t.task_id DESC
                """).fetchall()
                dependencies = conn.execute("""
                    SELECT d.task_id AS dependent_task_id, p.task_id, p.meeting_id,
                           p.item_id, p.task AS description, p.owner, p.deadline, p.status
                    FROM public.task_dependencies d
                    JOIN public.tasks p ON p.task_id = d.depends_on_task_id
                    ORDER BY d.task_id, p.task_id
                """).fetchall()
                employees = conn.execute('SELECT person_id, name FROM public.employees').fetchall()
            by_task = {}
            for dependency in dependencies:
                dependency['owners'] = parse_owner(dependency['owner'])
                by_task.setdefault(dependency['dependent_task_id'], []).append(dependency)
            for task in tasks:
                task['owners'] = parse_owner(task['owner'])
                task['dependencies'] = by_task.get(task['task_id'], [])
            names = {e['person_id']: e['name'] for e in employees}
            if include_clock:
                return tasks, names, clock
            return tasks, names
        except DatabaseError:
            raise
        except Exception:
            raise DatabaseError('Không đọc được PostgreSQL. Kiểm tra kết nối, quyền SELECT và schema DB.') from None

    def update_status(self, task_id, before, after):
        if after not in TRANSITIONS.get(before, ()):
            raise DatabaseError('Không được phép chuyển trạng thái này. Công việc bị chặn sẽ tự mở khóa khi các công việc tiền đề hoàn thành.')
        try:
            with self.connection_factory() as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                row = conn.execute("""
                    UPDATE public.tasks SET status = %s, updated_at = NOW()
                    WHERE task_id = %s AND status = %s
                    RETURNING task_id
                """, (after, task_id, before)).fetchone()
                if row is None:
                    raise DatabaseError('Task đã đổi trạng thái hoặc bị xóa. Hãy làm mới danh sách.')
                if after == 'done':
                    # Serialize competing completions sharing a child. This separate
                    # statement waits for the child lock; the UPDATE below then gets
                    # a fresh READ COMMITTED snapshot of all prerequisite statuses.
                    conn.execute("""
                        SELECT child.task_id
                        FROM public.tasks child
                        WHERE child.status = 'blocked'
                          AND EXISTS (
                              SELECT 1 FROM public.task_dependencies d
                              WHERE d.task_id = child.task_id
                                AND d.depends_on_task_id = %s
                          )
                        ORDER BY child.task_id
                        FOR UPDATE OF child
                    """, (task_id,)).fetchall()
                    conn.execute("""
                        UPDATE public.tasks child
                        SET status = 'ready', updated_at = NOW()
                        WHERE child.status = 'blocked'
                          AND EXISTS (
                              SELECT 1 FROM public.task_dependencies d
                              WHERE d.task_id = child.task_id
                                AND d.depends_on_task_id = %s
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM public.task_dependencies d
                              JOIN public.tasks parent
                                ON parent.task_id = d.depends_on_task_id
                              WHERE d.task_id = child.task_id
                                AND parent.status <> 'done'
                          )
                    """, (task_id,))
        except DatabaseError:
            raise
        except Exception:
            raise DatabaseError('Không cập nhật được PostgreSQL. Hãy làm mới để kiểm tra trạng thái và kết nối/quyền UPDATE.') from None


def filter_tasks(tasks, status=None, owner=None, meeting=None, search=''):
    query = search.strip().casefold()
    return [t for t in tasks
            if (status is None or t['status'] == status)
            and (owner is None or owner in t['owners'])
            and (meeting is None or t['meeting_id'] == meeting)
            and (not query or query in ' '.join(str(t.get(k) or '') for k in
                 ('task_id', 'meeting_id', 'item_id', 'description')).casefold())]
