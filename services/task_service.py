"""Task read/write adapter for session demo; no PostgreSQL writes."""
from copy import deepcopy
from .store import STATUSES, now, editable_changes


class TaskService:
    def __init__(self, store):
        self.store = store

    def list_tasks(self, status=None, owner=None, meeting=None, search=''):
        return deepcopy([i for i in self.store['items'].values()
            if i['expected_decision'] == 'confirmed' and i.get('review_status') != 'rejected'
            and (not status or i['status'] == status)
            and (not owner or owner in i['owners'])
            and (not meeting or i['meeting_id'] == meeting)
            and (not search or search.casefold() in (i['description'] + ' ' + i['item_id']).casefold())])

    def get(self, key):
        return next((i for i in self.list_tasks() if i['task_id'] == key), None)

    def related(self, key):
        task = self.get(key)
        return deepcopy([i for i in self.store['items'].values()
                         if task and i['meeting_id'] == task['meeting_id'] and i['task_id'] != key])

    def update_status(self, key, status):
        if status not in STATUSES or self.get(key) is None:
            raise ValueError('Task hoặc status không hợp lệ.')
        task = self.store['items'][key]
        before = task['status']
        task['status'] = status
        task['history'].append(dict(timestamp=now(), action='Update Status', before=before, status=status))

    def edit(self, key, **changes):
        if self.get(key) is None:
            raise ValueError('Không tìm thấy task.')
        updates = editable_changes(**changes)
        task = self.store['items'][key]
        before = {field: deepcopy(task[field]) for field in updates}
        task.update(updates)
        task['history'].append(dict(timestamp=now(), action='Edit', before=before, changes=updates))
