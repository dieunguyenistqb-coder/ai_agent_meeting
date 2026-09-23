"""Local preview alerts. Does not represent n8n, email queues or scheduling."""
from datetime import date
from .store import now


class MonitoringService:
    def __init__(self, task_service, review_service):
        self.tasks = task_service
        self.reviews = review_service

    def alerts(self, today=None):
        today = today or date.today()
        rows = []
        def add(item, kind, message, target='task'):
            rows.append(dict(type=kind, task_id=item['task_id'], item=item['item_id'],
                             message=message, timestamp=now(), target=target))
        for task in self.tasks.list_tasks():
            if task['status'] in ('done', 'completed'):
                continue
            if not task.get('owners'):
                add(task, 'unassigned', 'Công việc chưa có người phụ trách.')
            if not task.get('deadline'):
                add(task, 'missing deadline', 'Công việc chưa có hạn hoàn thành.')
            if task['status'] == 'blocked':
                add(task, 'blocked task', 'Task đang blocked; cần kiểm tra trạng thái/phụ thuộc.')
                continue
            try:
                deadline = date.fromisoformat(task['deadline']) if task['deadline'] else None
            except (ValueError, TypeError):
                deadline = None
            if deadline:
                remaining = (deadline - today).days
                if remaining < 0:
                    add(task, 'task overdue', f'Quá hạn {-remaining} ngày.')
                elif remaining <= 3:
                    add(task, 'task due soon', f'Đến hạn trong {remaining} ngày.')
        for item in self.reviews.pending():
            add(item, 'human review pending', item.get('review_reason') or 'Chờ review.', 'review')
        return rows
