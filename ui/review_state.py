"""Project human review actions onto a separate schema-preserving JSON snapshot."""
from copy import deepcopy

from services.store import task_key


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
                for field in ('description', 'owners', 'deadline'):
                    if field in event['changes']:
                        item[field] = deepcopy(event['changes'][field])
            item['expected_decision'] = 'not_task' if action == 'reject' else 'confirmed'
            item['review_reason'] = None
            changed = True
    state['reviewed_json'] = reviewed if changed else None
