"""Send final pipeline output to the n8n task workflow on demand."""
import os
from pathlib import Path

import requests
from dotenv import dotenv_values


N8N_WEBHOOK_URL = (
    os.environ.get("N8N_WEBHOOK_URL")
    or dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("N8N_WEBHOOK_URL")
    or "http://localhost:5678/webhook/task-input"
)


def send_to_n8n(final_json):
    """POST the unchanged final JSON once; propagate request errors to the UI."""
    response = requests.post(N8N_WEBHOOK_URL, json=final_json, timeout=30,
                             allow_redirects=False)
    response.raise_for_status()
    return response


class WorkflowRunError(ValueError):
    """User-facing message without exposing a webhook URL or response body."""


def workflow_b_url():
    return (os.environ.get('N8N_WORKFLOW_B_RUN_URL')
            or dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('N8N_WORKFLOW_B_RUN_URL')
            or '').strip()


def run_workflow_b():
    """One explicit POST, no retry or redirects; caller reloads DB afterward."""
    from urllib.parse import urlsplit
    url = workflow_b_url()
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    except ValueError:
        valid = False
    if not valid:
        raise WorkflowRunError('Chưa cấu hình địa chỉ dịch vụ kiểm tra hợp lệ.')
    try:
        response = requests.post(url, json={}, timeout=30, allow_redirects=False)
    except requests.Timeout:
        raise WorkflowRunError('Chưa nhận được phản hồi kịp thời. Kiểm tra có thể vẫn đang chạy; hãy làm mới danh sách trước khi thử lại.') from None
    except requests.RequestException:
        raise WorkflowRunError('Không nhận được phản hồi từ dịch vụ kiểm tra. Hãy kiểm tra kết nối và làm mới danh sách.') from None
    if not 200 <= response.status_code < 300:
        raise WorkflowRunError('Dịch vụ kiểm tra trả về lỗi. Hãy kiểm tra cấu hình và thử lại.')


REMINDER_STATUSES = {'sent', 'too_soon', 'done', 'no_email', 'not_found',
                     'invalid_task_id', 'error'}


def run_workflow_c_reminder(task_id):
    """Send only the integer task ID; Workflow C owns email and throttling."""
    if type(task_id) is not int or task_id <= 0:
        return 'invalid_task_id'
    url = (os.environ.get('N8N_WORKFLOW_C_REMINDER_URL')
           or dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('N8N_WORKFLOW_C_REMINDER_URL')
           or 'http://localhost:5678/webhook/task-reminder').strip()
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError
    except ValueError:
        raise WorkflowRunError('Địa chỉ dịch vụ nhắc nhở chưa hợp lệ.') from None
    try:
        response = requests.post(url, json={'task_id': task_id}, timeout=30,
                                 allow_redirects=False)
    except requests.Timeout:
        raise WorkflowRunError('Chưa nhận được phản hồi kịp thời. Nhắc nhở có thể đã được gửi; hãy làm mới danh sách trước khi thử lại.') from None
    except requests.RequestException:
        raise WorkflowRunError('Không thể kết nối hệ thống nhắc nhở. Vui lòng thử lại.') from None
    try:
        data = response.json()
    except ValueError:
        raise WorkflowRunError('Hệ thống nhắc nhở trả về phản hồi không hợp lệ.') from None
    status = data.get('status') if isinstance(data, dict) else None
    if not isinstance(status, str) or status not in REMINDER_STATUSES:
        raise WorkflowRunError('Hệ thống nhắc nhở trả về trạng thái không hợp lệ.')
    # Business rejections may use 4xx, but never treat HTTP failure as sent.
    if not 200 <= response.status_code < 300 and status == 'sent':
        raise WorkflowRunError('Hệ thống nhắc nhở trả về lỗi. Hãy làm mới trước khi thử lại.')
    return status
