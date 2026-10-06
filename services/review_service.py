"""Human review adapter. All writes affect the supplied session store only."""
from copy import deepcopy
from .store import now, editable_changes, task_key


OWNER_REQUIRED_MESSAGE = 'Vui lòng chọn người phụ trách trước khi xác nhận.'


def missing_task_owner(item):
    owners = item.get('owners')
    return item.get('content_type') == 'task_candidate' and (
        not isinstance(owners, list) or not owners
        or any(not isinstance(owner, str) or not owner.strip() for owner in owners))


def needs_owner_repair(item):
    return (item.get('expected_decision') == 'confirmed'
            and item.get('review_status') != 'rejected' and missing_task_owner(item))


class ReviewService:
    def __init__(self, store):
        self.store = store

    def save_added(self, meeting_id, changes, item_id=None):
        """Human-authorized draft in the existing review store, never a DB write."""
        from src.schemas import FinalItem
        items = [i for i in self.store['items'].values() if i['meeting_id'] == meeting_id]
        if meeting_id not in self.store['versions']:
            raise ValueError('Chưa có batch trích xuất để bổ sung.')
        if item_id is None:
            item_id = f"ITEM{max([int(i['item_id'][4:]) for i in items] or [0]) + 1:03d}"
        else:
            existing = self.store['items'].get(task_key(meeting_id, item_id), {})
            if existing.get('item_origin') != 'human_added' or existing.get('review_status') == 'rejected':
                raise ValueError('Không thể sửa công việc bổ sung này.')
        fields = editable_changes(changes['description'], changes['owners'], changes.get('deadline'))
        if not fields['owners']:
            raise ValueError('Vui lòng nhập người phụ trách.')
        data = FinalItem.model_validate(dict(
            **fields, item_id=item_id, content_type='task_candidate',
            source_excerpt=changes.get('source_excerpt', []),
            deadline_text=None, deadline_status='resolved' if fields['deadline'] else 'missing',
            priority=changes.get('priority'), commitment='explicit',
            depends_on=changes.get('depends_on', []), expected_decision='confirmed',
            review_reason='Added manually by human reviewer')).model_dump()
        targets = {i['item_id'] for i in items if i.get('review_status') != 'rejected'
                   and i['content_type'] == 'task_candidate'}
        if any(dep == item_id or dep not in targets for dep in data['depends_on']):
            raise ValueError('Công việc tiền đề phải tồn tại trong batch và không được là chính nó.')
        key = task_key(meeting_id, item_id)
        previous = self.store['items'].get(key)
        history = deepcopy(previous['history']) if previous else []
        history.append(dict(timestamp=now(), action='human_edit' if previous else 'human_add',
                            before={field: deepcopy(previous.get(field)) for field in FinalItem.model_fields} if previous else None, changes=deepcopy(data)))
        self.store['items'][key] = dict(data, task_id=key, meeting_id=meeting_id,
            item_origin='human_added', review_status='confirmed_by_human', status='not_started',
            reviewed_at=now(), history=history)
        return item_id

    def discard_added(self, key):
        item = self.store['items'][key]
        if item.get('item_origin') != 'human_added':
            raise ValueError('Không phải công việc bổ sung thủ công.')
        item['review_status'] = 'rejected'
        item['history'].append(dict(timestamp=now(), action='human_discard'))

    def validate_item(self, item):
        from src.schemas import RawItem, RawMeetingOutput
        from src.schema_validator import validate_business_rules
        if missing_task_owner(item):
            raise ValueError(OWNER_REQUIRED_MESSAGE)
        if not item.get('description', '').strip():
            raise ValueError('Nội dung công việc không được rỗng.')
        raw = RawItem.model_validate({k: item[k] for k in RawItem.model_fields if k in item})
        targets = {i['item_id'] for i in self.store['items'].values()
                   if i['meeting_id'] == item['meeting_id'] and i.get('review_status') != 'rejected'}
        try:
            validate_business_rules(RawMeetingOutput(meeting_id=item['meeting_id'], items=[raw]),
                dependency_item_ids=targets,
                human_authorized_ids={item['item_id']} if item.get('item_origin') == 'human_added' else set())
        except ValueError as error:
            import re
            owners = re.findall(r"owner '([^']+)' không xuất hiện", str(error))
            if owners:
                raise ValueError('\n'.join(f"Người phụ trách '{owner}' không xuất hiện trong trích dẫn. Vui lòng chọn/sửa lại." for owner in owners)) from error
            raise

    def reopen_invalid(self, meeting_id=None):
        """Recover stale confirmations while preserving edits and history."""
        errors = {}
        for key, item in self.store['items'].items():
            if meeting_id is not None and item['meeting_id'] != meeting_id:
                continue
            if item.get('review_status') == 'rejected' or item.get('expected_decision') != 'confirmed':
                continue
            try:
                self.validate_item(item)
            except ValueError as error:
                item['draft'] = {k: deepcopy(item.get(k)) for k in ('description', 'owners', 'deadline')}
                item['validation_errors'] = [str(error)]
                item['review_status'] = 'pending'
                item['expected_decision'] = 'human_review'
                item['history'].append(dict(timestamp=now(), action='reopen_invalid', changes={}))
                errors[item['item_id']] = [str(error)]
        return errors

    def pending(self):
        return deepcopy([i for i in self.store['items'].values()
                         if (i['expected_decision'] == 'human_review' and i['review_status'] == 'pending')
                         or (needs_owner_repair(i) and i.get('item_origin') != 'human_added')])

    def reviewed_today(self):
        return sum((i.get('reviewed_at') or '').startswith(now()[:10]) for i in self.store['items'].values())

    def decide(self, key, action, changes=None):
        item = self.store['items'][key]
        if item['review_status'] != 'pending' and not needs_owner_repair(item):
            raise ValueError('Item đã được review.')
        if action not in ('confirm', 'reject', 'edit'):
            raise ValueError('Review action không hợp lệ.')
        if action == 'confirm' and item.get('draft'):
            action, changes = 'edit', item['draft']
        updates = editable_changes(**changes) if action == 'edit' else {}
        if action == 'edit':
            updates.update(normalize_review_deadline(item, updates))
        if action != 'reject' and missing_task_owner(dict(item, **updates)):
            raise ValueError(OWNER_REQUIRED_MESSAGE)
        if action != 'reject':
            try:
                self.validate_item(dict(item, **updates))
            except ValueError as error:
                item['draft'] = {k: deepcopy(dict(item, **updates).get(k)) for k in ('description', 'owners', 'deadline')}
                item['validation_errors'] = [str(error)]
                raise
        item.pop('draft', None)
        item.pop('validation_errors', None)
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
