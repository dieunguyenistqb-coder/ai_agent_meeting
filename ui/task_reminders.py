"""Session guard and safe presentation for explicit manual reminder requests."""
import streamlit as st
from services.n8n_service import run_workflow_c_reminder, WorkflowRunError

MESSAGES = {
    'sent': ('success', 'Đã gửi nhắc nhở.'),
    'too_soon': ('info', 'Công việc vừa được nhắc nhở. Vui lòng chờ trước khi gửi lại.'),
    'done': ('info', 'Công việc đã hoàn thành, không cần gửi nhắc nhở.'),
    'no_email': ('warning', 'Chưa có email người phụ trách để gửi nhắc nhở.'),
    'not_found': ('warning', 'Không tìm thấy công việc. Vui lòng làm mới danh sách.'),
    'invalid_task_id': ('warning', 'Mã công việc không hợp lệ. Vui lòng làm mới danh sách.'),
    'error': ('error', 'Không thể gửi nhắc nhở. Vui lòng thử lại sau.'),
}


def queue_reminder(task_id):
    if st.session_state.get('reminder_busy') is None:
        st.session_state.reminder_busy = task_id
        st.session_state.reminder_pending = task_id


def reminder_button(task_id):
    st.button('Gửi nhắc nhở', key=f'remind_{task_id}',
              disabled=st.session_state.get('reminder_busy') is not None,
              on_click=queue_reminder, args=(task_id,))
    if st.session_state.get('reminder_pending') == task_id:
        st.session_state.pop('reminder_pending')
        try:
            with st.spinner('Đang gửi nhắc nhở...'):
                status = run_workflow_c_reminder(task_id)
            st.session_state.reminder_result = MESSAGES[status]
        except WorkflowRunError as error:
            st.session_state.reminder_result = ('warning', str(error))
        finally:
            st.session_state.reminder_busy = None
        # A fresh rerun reads DB, including last_reminded_at, without another POST.
        st.rerun()
