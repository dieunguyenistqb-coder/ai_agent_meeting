from datetime import date
from html import escape
from .formatters import value_text, label, task_code, STATUS_LABELS, CONTENT_TYPE_LABELS, DECISION_LABELS, COMMITMENT_LABELS
import streamlit as st
from services.store import STATUSES


def banner():
    st.caption('Chế độ staging — Dữ liệu chỉ tồn tại trong phiên hiện tại; chưa gửi email hoặc tạo lịch.')


def edit_form(key, item, label, save):
    with st.form(key):
        description = st.text_area('Description', value=value_text(item.get('description'), ''))
        owners = st.text_input('Owners (phân tách bằng dấu phẩy)', value=value_text(item.get('owners'), ''))
        try:
            initial = date.fromisoformat(item['deadline']) if item.get('deadline') else None
        except (ValueError, TypeError):
            initial = None
        deadline = st.date_input('Deadline', value=initial)
        if st.form_submit_button(label):
            try:
                save(dict(description=description, owners=owners.split(','),
                          deadline=deadline.isoformat() if deadline else None))
            except ValueError as error:
                st.error(str(error))
            else:
                st.rerun()


def review_screen(service):
    st.subheader('Human Review')
    banner()
    pending = service.pending()
    a, b = st.columns(2)
    a.metric('Items to review', len(pending))
    b.metric('Reviewed today (UTC)', service.reviewed_today())
    if not pending:
        st.info('Không có item chờ review trong session. Chạy extraction để nạp dữ liệu.')
        return
    st.dataframe([{k: i.get(k) for k in ('item_id', 'meeting_id', 'description', 'owners', 'deadline', 'review_reason')}
                  | {'actions': 'Confirm / Reject / Edit bên dưới'} for i in pending], hide_index=True, width='stretch')
    for item in pending:
        key = item['task_id']
        with st.expander(f"{item['meeting_id']} · {item['item_id']} · {item['description']}"):
            st.markdown(':orange[human_review]')
            st.text(item.get('review_reason') or '—')
            st.code('\n'.join(item['source_excerpt']), language=None, wrap_lines=True)
            a, b = st.columns(2)
            if a.button('Confirm', key=f'confirm:{key}'):
                service.decide(key, 'confirm'); st.rerun()
            if b.button('Reject', key=f'reject:{key}'):
                service.decide(key, 'reject'); st.rerun()
            with st.expander('Edit'):
                edit_form(f'review_edit:{key}', item, 'Save & Confirm (session)',
                          lambda changes, key=key: service.decide(key, 'edit', changes))


def dashboard(service):
    st.subheader('Task Dashboard')
    banner()
    tasks = service.list_tasks()
    for col, label, count in zip(st.columns(4), ('Confirmed', 'In Progress', 'Blocked', 'Ready'),
        (len(tasks), sum(i['status'] == 'in_progress' for i in tasks),
         sum(i['status'] == 'blocked' for i in tasks), sum(i['status'] == 'ready' for i in tasks))):
        col.metric(label, count)
    a, b, c, d = st.columns(4)
    status = a.selectbox('Status', ['All', *STATUSES])
    owner = b.selectbox('Owner', ['All', *sorted({o for i in tasks for o in i['owners']})])
    meeting = c.selectbox('Meeting', ['All', *sorted({i['meeting_id'] for i in tasks})])
    search = d.text_input('Search text')
    filtered = service.list_tasks(None if status == 'All' else status, None if owner == 'All' else owner,
                                  None if meeting == 'All' else meeting, search)
    if not filtered:
        st.info('Không có task phù hợp. Task confirmed từ extraction/review sẽ xuất hiện tại đây.')
        return
    st.dataframe([{k: i.get(k) for k in ('task_id', 'description', 'owners', 'deadline', 'status', 'meeting_id')}
                  | {'action': 'View bên dưới'} for i in filtered], hide_index=True, width='stretch')
    for task in filtered:
        a, b = st.columns([5, 1])
        a.text(f"{task['meeting_id']} · {task['item_id']} · {task['description']}")
        if b.button('View', key=f"view:{task['task_id']}"):
            st.session_state.selected_task = task['task_id']; st.rerun()


def task_detail(service, key):
    st.subheader('Chi tiết công việc')
    banner()
    if st.button('← Quay lại danh sách'):
        st.session_state.selected_task = None; st.rerun()
    task = service.get(key)
    if not isinstance(task, dict):
        st.warning('Task không còn trong session hiện tại.'); return
    status = label(task.get('status'), STATUS_LABELS)
    decision = label(task.get('expected_decision'), DECISION_LABELS)
    decision_color = {'confirmed': 'green', 'human_review': 'orange', 'not_task': 'gray'}.get(
        str(task.get('expected_decision')), 'gray')
    status_color = 'red' if task.get('status') == 'blocked' else ''
    st.markdown(f"""<div class="task-card">
    <div class="task-description">{escape(value_text(task.get('description')))}</div>
    <div class="task-badges"><span class="task-badge">Mã công việc: {escape(task_code(task))}</span>
    <span class="task-badge {status_color}">{escape(status)}</span>
    <span class="task-badge {decision_color}">{escape(decision)}</span></div></div>""", unsafe_allow_html=True)
    for pair in (
        (('Người phụ trách', value_text(task.get('owners'), 'Chưa phân công')),
         ('Hạn hoàn thành', value_text(task.get('deadline'), 'Chưa xác định'))),
        (('Trạng thái', status), ('Loại nội dung', label(task.get('content_type'), CONTENT_TYPE_LABELS))),
        (('Mức độ cam kết', label(task.get('commitment'), COMMITMENT_LABELS)), ('Kết quả xác minh', decision))):
        for column, (heading, value) in zip(st.columns(2), pair):
            column.caption(heading)
            column.text(value)
    with st.expander('Thông tin chi tiết'):
        for heading, field in (('Trích dẫn cuộc họp', 'source_excerpt'), ('Phụ thuộc', 'depends_on'),
                               ('Tình trạng hạn hoàn thành', 'deadline_status'), ('Lý do cần kiểm tra', 'review_reason')):
            st.caption(heading)
            st.text(value_text(task.get(field)))
        st.caption('Dữ liệu công việc đầy đủ')
        st.json(task)
    with st.expander('Công việc liên quan · cùng cuộc họp'):
        st.dataframe(service.related(key), hide_index=True, width='stretch')
    with st.expander('Lịch sử thao tác trong phiên'):
        st.json(task.get('history') or [])
    with st.expander('Chỉnh sửa'):
        edit_form(f'task_edit:{key}', task, 'Lưu trong phiên', lambda changes: service.edit(key, **changes))
    with st.form(f'status:{key}'):
        current = task.get('status')
        index = STATUSES.index(current) if current in STATUSES else None
        status = st.selectbox('Cập nhật trạng thái', STATUSES, index=index,
                              format_func=lambda value: label(value, STATUS_LABELS))
        if st.form_submit_button('Cập nhật trạng thái', disabled=status is None):
            service.update_status(key, status); st.rerun()


def monitoring(service, task_enabled, review_enabled):
    st.subheader('Monitoring & Alerts')
    banner()
    alerts = service.alerts()
    for col, label, kind in zip(st.columns(3), ('Overdue Tasks', 'Due Soon', 'Blocked Tasks'),
                               ('task overdue', 'task due soon', 'blocked task')):
        col.metric(label, sum(a['type'] == kind for a in alerts))
    st.caption('Preview tính theo ngày hiện tại; Due Soon ≤ 3 ngày. Timestamp là thời điểm kiểm tra. Chưa có dữ liệu hàng đợi email/automation.')
    if not alerts:
        st.info('Không có alert từ dữ liệu session.'); return
    st.dataframe([{k: a[k] for k in ('type', 'item', 'message', 'timestamp')} for a in alerts], hide_index=True, width='stretch')
    for index, alert in enumerate(alerts):
        a, b = st.columns([5, 1])
        a.text(f"{alert['type']} · {alert['item']} · {alert['message']}")
        enabled = task_enabled if alert['target'] == 'task' else review_enabled
        if b.button('View', key=f'alert:{index}', disabled=not enabled):
            st.session_state.navigate_to = 'Task Dashboard' if alert['target'] == 'task' else 'Human Review'
            st.session_state.selected_task = alert['task_id'] if alert['target'] == 'task' else None
            st.rerun()
