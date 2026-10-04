"""Human review adapter. All writes affect the supplied session store only."""
from copy import deepcopy
from .store import now, editable_changes


class ReviewService:
    def __init__(self, store):
        self.store = store

    def pending(self):
        return deepcopy([i for i in self.store['items'].values()
                         if i['expected_decision'] == 'human_review' and i['review_status'] == 'pending'])

    def reviewed_today(self):
        return sum((i.get('reviewed_at') or '').startswith(now()[:10]) for i in self.store['items'].values())

    def decide(self, key, action, changes=None):
        item = self.store['items'][key]
        if item['review_status'] != 'pending':
            raise ValueError('Item đã được review.')
        if action not in ('confirm', 'reject', 'edit'):
            raise ValueError('Review action không hợp lệ.')
        updates = editable_changes(**changes) if action == 'edit' else {}
        if action == 'edit':
            updates.update(normalize_review_deadline(item, updates))
        before = {field: deepcopy(item.get(field)) for field in updates}
        item.update(updates)
        item['review_status'] = 'rejected' if action == 'reject' else 'confirmed_by_human'
        if action != 'reject':
            # Explicit human approval, not an LLM or Decision Policy inference.
            item['expected_decision'] = 'confirmed'
        item['reviewed_at'] = now()
        item['history'].append(dict(timestamp=now(), action=action, before=before, changes=updates))


def normalize_review_deadline(item, changes):
    """Normalize an explicit Edit deadline, without inferring an unresolved date."""
    if 'deadline' not in changes:
        return {}
    deadline = changes['deadline']
    if deadline is not None:
        return {'deadline_status': 'resolved'}
    if item.get('deadline') is not None or item.get('deadline_status') in ('missing', 'resolved'):
        return {'deadline_status': 'missing'}
    # Editing other fields with an empty date must not erase ambiguity/conflict.
    return {}
