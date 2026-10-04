"""Project human review actions onto a separate schema-preserving JSON snapshot."""
from copy import deepcopy

from services.store import task_key
from services.review_service import normalize_review_deadline


def refresh_reviewed_json(state):
    final = state.get('final_object')
    if final is None:
        state['final_json'] = None
        state['reviewed_json'] = None
        return
    original = final.model_dump() if hasattr(final, 'model_dump') else final
    if state.get('final_json') != original:
        state['final_json'] = deepcopy(original)
        state['reviewed_json'] = None
    reviewed = deepcopy(state['final_json'])
    changed = False
    stored_items = state.get('demo_store', {}).get('items', {})
    for item in reviewed['items']:
        stored = stored_items.get(task_key(reviewed['meeting_id'], item['item_id']), {})
        for event in stored.get('history', []):
            action = event.get('action')
            if action not in ('confirm', 'edit', 'reject'):
                continue
            if action == 'edit':
                # Derive before replacing the date; also repairs older audit events.
                normalized = normalize_review_deadline(item, event['changes'])
                for field in ('description', 'owners', 'deadline'):
                    if field in event['changes']:
                        item[field] = deepcopy(event['changes'][field])
                item.update(normalized)
            item['expected_decision'] = 'not_task' if action == 'reject' else 'confirmed'
            item['review_reason'] = None
            changed = True
    rejected = {key for key, item in stored_items.items() if item.get('review_status') == 'rejected'}
    reviewed['items'] = [item for item in reviewed['items']
                         if task_key(reviewed['meeting_id'], item['item_id']) not in rejected]
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
    if pending_batch_items(state):
        raise ValueError('Còn item chưa được xác nhận hoặc bỏ. Vui lòng xử lý toàn bộ batch.')
    refresh_reviewed_json(state)
    original = state['final_json']
    ids = [item['item_id'] for item in original['items']]
    if len(ids) != len(set(ids)):
        raise ValueError('Batch có item_id trùng nhau.')
    data = state.get('reviewed_json') or original
    final = FinalMeetingOutput.model_validate(data)
    if any(item.expected_decision == 'human_review' for item in final.items):
        raise ValueError('Batch còn item cần xác nhận.')
    validate_business_rules(final)
    return final.model_dump()
