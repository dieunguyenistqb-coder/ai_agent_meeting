"""Explicitly loaded fictional data and session-only reset/projections."""
from copy import deepcopy
import json
from services.store import new_store, sync_meeting, task_key
from services.task_service import TaskService
from services.review_service import ReviewService
from services.monitoring_service import MonitoringService


def reset_session(state):
    # Preserve authentication and API budgets, including the existing request lock.
    for key in list(state):
        if str(key).startswith(('review_edit:', 'task_edit:', 'status:', 'confirm:', 'reject:')):
            state.pop(key, None)
    state['confirm_reset'] = False
    for key in ('transcript', 'raw_output', 'validated_object', 'final_object',
                'reviewed_items', 'tasks', 'alerts', 'demo_store', 'selected_task',
                'saved_upload', 'transcript_upload', 'upload_identity', 'meeting_id',
                'meeting_date', 'metadata_error', 'result_input', 'pipeline_status',
                'error_message', 'user_error_message', 'data_source'):
        state.pop(key, None)


def demo_snapshot():
    """Hand-written fictional example; no local dataset or provider reads."""
    items = []
    for number, description, owners, decision in (
        (1, 'Soạn checklist cho dự án minh họa', ['Nhân vật A'], 'confirmed'),
        (2, 'Chuẩn bị tài liệu hướng dẫn minh họa', [], 'human_review'),
        (3, 'Kiểm tra bản thiết kế minh họa', ['Nhân vật B'], 'confirmed')):
        items.append(dict(item_id=f'ITEM{number:03}', description=description,
            source_excerpt=[f'Nhân vật demo: {description}.'], owners=owners,
            deadline='2026-10-01' if number == 1 else None,
            deadline_text='01-10-2026' if number == 1 else None,
            deadline_status='resolved' if number == 1 else 'missing',
            content_type='task_candidate', commitment='explicit', depends_on=[],
            priority=None, temporal_warning=None, expected_decision=decision,
            review_reason='Chưa có người phụ trách' if number == 2 else None))
    return dict(meeting_id='DEMO', meeting_date=None, meeting_date_evidence=None, items=items)


def load_demo(state):
    reset_session(state)
    final = demo_snapshot()
    raw = deepcopy(final)
    for item in raw['items']:
        item.pop('expected_decision')
        item.pop('review_reason')
    state.update(transcript='Dữ liệu minh họa hoàn toàn giả lập.', raw_output=json.dumps(raw, ensure_ascii=False),
                 validated_object=None, final_object=final, data_source='demo',
                 result_input=None, error_message=None, user_error_message=None)
    state['demo_store'] = new_store()
    sync_meeting(state['demo_store'], final)
    TaskService(state['demo_store']).update_status(task_key('DEMO', 'ITEM003'), 'blocked')
    refresh_views(state)


def refresh_views(state):
    state.setdefault('transcript', '')
    state.setdefault('demo_store', new_store())
    sync_meeting(state['demo_store'], state.get('final_object'))
    tasks = TaskService(state['demo_store'])
    reviews = ReviewService(state['demo_store'])
    state['tasks'] = tasks.list_tasks()
    state['reviewed_items'] = deepcopy([i for i in state['demo_store']['items'].values()
                                       if i.get('reviewed_at')])
    state['alerts'] = MonitoringService(tasks, reviews).alerts()
