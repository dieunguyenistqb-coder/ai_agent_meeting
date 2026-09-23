"""Display-only labels and safe formatting; never modifies task values."""
import json

STATUS_LABELS = {'not_started': 'Chưa bắt đầu', 'in_progress': 'Đang thực hiện',
                 'completed': 'Đã hoàn thành', 'done': 'Đã hoàn thành',
                 'blocked': 'Đang bị chặn', 'ready': 'Sẵn sàng'}
CONTENT_TYPE_LABELS = {'task_candidate': 'Công việc cần xác minh', 'information': 'Thông tin',
                       'decision': 'Quyết định', 'proposal': 'Đề xuất'}
DECISION_LABELS = {'confirmed': 'Đã xác nhận', 'human_review': 'Cần con người kiểm tra',
                   'not_task': 'Không phải công việc', 'rejected': 'Đã từ chối'}
COMMITMENT_LABELS = {'explicit': 'Rõ ràng', 'tentative': 'Dự kiến', 'implicit': 'Ngầm định',
                     'ambiguous': 'Chưa rõ ràng', 'not_applicable': 'Không áp dụng'}


def value_text(value, missing='Chưa có thông tin'):
    if value is None or value == '' or value == [] or value == {}:
        return missing
    if isinstance(value, str):
        return value if value.strip() else missing
    if isinstance(value, (list, tuple)):
        return ', '.join(value_text(v) for v in value) if value else missing
    return str(value)


def label(value, mapping):
    return mapping.get(value, value_text(value)) if isinstance(value, str) else value_text(value)


def task_code(task):
    value = task.get('task_id')
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
        except (ValueError, TypeError):
            pass
    if isinstance(value, (list, tuple)) and value:
        return ' · '.join(value_text(part) for part in value)
    if task.get('meeting_id') and task.get('item_id'):
        return f"{value_text(task['meeting_id'])} · {value_text(task['item_id'])}"
    return value_text(value)
