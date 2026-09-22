from copy import deepcopy
from datetime import datetime, timezone
import json

STATUSES = ('not_started', 'in_progress', 'blocked', 'ready', 'done')


def now():
    return datetime.now(timezone.utc).isoformat()


def task_key(meeting_id, item_id):
    return json.dumps([meeting_id, item_id], ensure_ascii=False)


def new_store():
    return dict(items={}, versions={})


def sync_meeting(store, final):
    """Import a snapshot once; changed extraction replaces only that meeting."""
    if final is None:
        return
    data = final.model_dump() if hasattr(final, 'model_dump') else final
    version = json.dumps(data, sort_keys=True, ensure_ascii=False)
    mid = data['meeting_id']
    if store['versions'].get(mid) == version:
        return
    store['items'] = {k: v for k, v in store['items'].items() if v['meeting_id'] != mid}
    for item in data['items']:
        key = task_key(mid, item['item_id'])
        store['items'][key] = dict(deepcopy(item), task_id=key, meeting_id=mid,
            status='not_started', review_status='pending' if item['expected_decision'] == 'human_review' else None,
            reviewed_at=None, history=[dict(timestamp=now(), action='Imported extraction into demo session')])
    store['versions'][mid] = version


def editable_changes(description, owners, deadline):
    from datetime import date
    if not description.strip():
        raise ValueError('Description không được để trống.')
    if not isinstance(owners, list) or any(not isinstance(owner, str) for owner in owners):
        raise ValueError('Owners phải là danh sách tên.')
    if deadline is not None:
        if date.fromisoformat(deadline).isoformat() != deadline:
            raise ValueError('Deadline phải có dạng YYYY-MM-DD.')
    return dict(description=description.strip(), owners=[o.strip() for o in owners if o.strip()], deadline=deadline)
