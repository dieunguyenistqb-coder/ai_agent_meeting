"""Project human review actions onto a separate schema-preserving JSON snapshot."""
from copy import deepcopy

from services.store import task_key
from services.review_service import normalize_review_deadline, missing_task_owner


def rebuild_final_json(original, stored_items):
    """Pure projection: never write to store, generate IDs or replay add actions."""
    reviewed = deepcopy(original)
    changed = False
    for item in reviewed['items']:
        stored = stored_items.get(task_key(reviewed['meeting_id'], item['item_id']), {})
        for event in stored.get('history', []):
            action = event.get('action')
            if action not in ('confirm', 'edit', 'reject', 'reopen_invalid'):
                continue
            if action == 'edit':
                # Derive before replacing the date; also repairs older audit events.
                normalized = normalize_review_deadline(item, event['changes'])
                for field in ('description', 'owners', 'deadline'):
                    if field in event['changes']:
                        item[field] = deepcopy(event['changes'][field])
                item.update(normalized)
            item['expected_decision'] = ('human_review' if action == 'reopen_invalid' else
                                         'not_task' if action == 'reject' else 'confirmed')
            item['review_reason'] = None
            changed = True
    rejected = {key for key, item in stored_items.items() if item.get('review_status') == 'rejected'}
    reviewed['items'] = [item for item in reviewed['items']
                         if task_key(reviewed['meeting_id'], item['item_id']) not in rejected]
    from src.schemas import FinalItem
    for stored in stored_items.values():
        if (stored.get('meeting_id') == reviewed['meeting_id']
                and stored.get('item_origin') == 'human_added'
                and stored.get('review_status') == 'confirmed_by_human'):
            if any(item['item_id'] == stored['item_id'] for item in reviewed['items']):
                raise ValueError(f"Trùng item_id khi ghép công việc bổ sung: {stored['item_id']}")
            reviewed['items'].append({field: deepcopy(stored[field])
                                      for field in FinalItem.model_fields if field in stored})
            changed = True
    return reviewed, changed


def refresh_reviewed_json(state):
    final = state.get('final_object')
    if final is None:
        state['final_json'] = None
        state['reviewed_json'] = None
        return
    original = final.model_dump() if hasattr(final, 'model_dump') else final
    stored = state.get('demo_store', {}).get('items', {})
    print('REBUILD BEFORE:', [(i['item_id'], i['description']) for i in original['items']])
    print('REBUILD STORE:', [(i['item_id'], i['description'], i.get('item_origin', 'model'))
                             for i in stored.values() if i['meeting_id'] == original['meeting_id']])
    reviewed, changed = rebuild_final_json(original, stored)
    print('REBUILD AFTER:', [(i['item_id'], i['description']) for i in reviewed['items']])
    state['final_json'] = deepcopy(original)
    state['reviewed_json'] = reviewed if changed else None


def pending_batch_items(state):
    """Only the active extraction batch controls submission."""
    final = state.get('final_object')
    if final is None:
        return []
    original = final.model_dump() if hasattr(final, 'model_dump') else final
    stored = state.get('demo_store', {}).get('items', {})
    return [item for item in original['items']
            if item['expected_decision'] == 'human_review'
            and stored.get(task_key(original['meeting_id'], item['item_id']), {}).get('review_status')
            not in ('confirmed_by_human', 'rejected')]


def build_submission(state):
    """Rebuild and validate without rerunning extraction or Decision Policy."""
    from src.schemas import FinalMeetingOutput
    from src.schema_validator import validate_business_rules
    if state.get('final_object') is None:
        raise ValueError('Chưa có kết quả để gửi.')
    from services.review_service import ReviewService
    final_source = state['final_object']
    mid = final_source.meeting_id if hasattr(final_source, 'meeting_id') else final_source['meeting_id']
    service = ReviewService(state['demo_store'])
    service.reopen_invalid(mid)
    item_errors = {i['item_id']: i['validation_errors'] for i in service.store['items'].values()
                   if i['meeting_id'] == mid and i.get('validation_errors') and i.get('review_status') != 'rejected'}
    state['item_validation_errors'] = item_errors
    if item_errors:
        refresh_reviewed_json(state)
        raise ValueError('Cần sửa công việc: ' + ', '.join(item_errors) + '. Mở Xác nhận thủ công để chỉnh sửa.')
    if pending_batch_items(state):
        raise ValueError('Còn item chưa được xác nhận hoặc bỏ. Vui lòng xử lý toàn bộ batch.')
    refresh_reviewed_json(state)
    original = state['final_json']
    ids = [item['item_id'] for item in original['items']]
    if len(ids) != len(set(ids)):
        raise ValueError('Batch có item_id trùng nhau.')
    data = state.get('reviewed_json') or original
    invalid_ids = [item['item_id'] for item in data['items']
                   if item.get('expected_decision') == 'confirmed' and missing_task_owner(item)]
    if invalid_ids:
        raise ValueError('Thiếu người phụ trách: ' + ', '.join(invalid_ids)
                         + '. Mở Xác nhận thủ công để sửa.')
    final = FinalMeetingOutput.model_validate(data)
    if any(item.expected_decision == 'human_review' for item in final.items):
        raise ValueError('Batch còn item cần xác nhận.')
    ids = [item.item_id for item in final.items]
    if len(ids) != len(set(ids)):
        raise ValueError('Batch có item_id trùng nhau.')
    for item in final.items:
        if not item.description.strip():
            raise ValueError(f'{item.item_id}: Nội dung công việc không được rỗng.')
    human_ids = {item['item_id'] for item in state.get('demo_store', {}).get('items', {}).values()
                 if item.get('meeting_id') == final.meeting_id
                 and item.get('item_origin') == 'human_added'
                 and item.get('review_status') == 'confirmed_by_human'}
    validate_business_rules(final, human_authorized_ids=human_ids)
    return final.model_dump()
