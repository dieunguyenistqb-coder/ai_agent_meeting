"""Task dashboard backed exclusively by PostgreSQL."""
import time
from datetime import date
from html import escape

import streamlit as st

from services.database_service import DatabaseError, TRANSITIONS, filter_tasks
from ui.formatters import task_code
from ui.task_reminders import reminder_button
from ui.task_styles import CSS, TONES, badge
from services.monitoring_service import ALERT_LABELS, attention_tasks
from services.n8n_service import workflow_b_url, run_workflow_b, WorkflowRunError

LABELS = {'ready': 'Chưa bắt đầu', 'in_progress': 'Đang thực hiện',
          'blocked': 'Bị chặn', 'done': 'Hoàn thành'}


def owner_text(task, employees):
    return ', '.join(f'{o} · {employees[o]}' if o in employees else o
                     for o in task['owners']) or 'Chưa phân công'


def dependency_summary(task):
    dependencies = task.get('dependencies', [])
    if task['status'] != 'blocked' or not dependencies:
        return ''
    # Show an unfinished prerequisite first; retain all prerequisites in details.
    pending = [d for d in dependencies if d['status'] != 'done']
    shown = pending or dependencies
    suffix = f" +{len(shown) - 1}" if len(shown) > 1 else ''
    return f"↳ bởi {task_code(shown[0])}{suffix}"


def deadline_text(value):
    # Preserve the ISO date presentation used by the existing task details.
    return value.isoformat() if value is not None else 'Chưa xác định'


def prerequisite_overdue(task, today=None):
    return (task['status'] != 'done' and task.get('deadline') is not None
            and task['deadline'] < (today or date.today()))


def task_table(tasks, owners, today=None):
    """Escaped HTML provides a smaller second line without adding a column."""
    headers = ('Mã công việc', 'Mô tả', 'Người phụ trách',
               'Hạn hoàn thành', 'Trạng thái', 'Cảnh báo')
    rows = []
    for task in tasks:
        groups = task.get('alert_groups', [])
        kind = next((g for g in ('overdue', 'blocked', 'due_soon') if g in groups), 'ready')
        code = f'<span class="task-dot tone-{TONES[kind]}"></span>{escape(task_code(task))}'
        deadline = escape(deadline_text(task['deadline']))
        if task['deadline'] is not None:
            deadline = '<span class="task-muted">▦</span> ' + deadline
        if today and task['deadline'] and any(g in groups for g in ('overdue','due_soon')):
            days = (task['deadline'] - today).days
            hint = f'Quá hạn {-days} ngày' if days < 0 else ('Đến hạn hôm nay' if days == 0 else f'Còn {days} ngày')
            tone = 'overdue' if days < 0 else 'due_soon'
            deadline += f'<small class="deadline-{tone}">{hint}</small>'
        cells = (f'<td class="task-code">{code}</td><td>{escape(task["description"])}</td>'
                 f'<td>{escape(owners(task))}</td><td>{deadline}</td>')
        status = badge(LABELS.get(task['status'], task['status']), task['status'])
        summary = dependency_summary(task)
        if summary:
            status += f'<small title="{escape(summary, quote=True)}">{escape(summary)}</small>'
        alerts = ''.join(badge(ALERT_LABELS[g], g) for g in groups) or '<span class="task-muted">—</span>'
        rows.append(f'<tr>{cells}<td>{status}</td><td>{alerts}</td></tr>')
    return """

<div class="meeting-task-list"><table aria-label="Danh sách công việc">
<colgroup><col style="width:16%"><col style="width:25%"><col style="width:17%">
<col style="width:12%"><col style="width:17%"><col style="width:13%"></colgroup>
<thead><tr>""" + ''.join(f'<th scope="col">{h}</th>' for h in headers) + (
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def dependency_details(task, owners, today=None):
    dependencies = task.get('dependencies', [])
    if not dependencies:
        return
    st.markdown('#### Công việc tiền đề')
    for dependency in dependencies:
        st.text(f"{task_code(dependency)} — {dependency['description']}")
        st.text(f"Người phụ trách: {owners(dependency)}")
        st.text(f"Hạn hoàn thành: {deadline_text(dependency['deadline'])}")
        st.text(f"Trạng thái: {LABELS.get(dependency['status'], 'Chưa sẵn sàng')}")
        if prerequisite_overdue(dependency, today):
            st.warning('⚠️ Công việc tiền đề đã quá hạn')
    if task['status'] == 'blocked':
        st.info("Công việc này sẽ tự động chuyển sang 'Chưa bắt đầu' khi tất cả công việc tiền đề đã hoàn thành.")


def clear_filters():
    for key in ('db_status', 'db_owner', 'db_alert_group', 'db_meeting'):
        st.session_state[key] = None
    st.session_state.db_search = ''


def dashboard(service):
    st.markdown(CSS, unsafe_allow_html=True)
    with st.container(key='task_workspace'):
        render_workspace(service)


def queue_alert_check():
    if not st.session_state.get('alert_check_busy'):
        st.session_state.alert_check_busy = True
        st.session_state.alert_check_pending = True


def render_workspace(service):
    title, actions = st.columns([1.15, 1], gap="large")
    title.subheader('Theo dõi công việc & cảnh báo')
    title.caption('Quản lý công việc, theo dõi tiến độ và các cảnh báo quan trọng.')
    with actions.container(key='task_header_actions'):
        timestamp = st.empty()
        refresh, run = st.columns([1, 1.2], gap='small')
    refresh.button('Làm mới danh sách', key='db_refresh', width='stretch')
    run.button('Kiểm tra cảnh báo ngay', key='run_alert_check',
               disabled=not workflow_b_url() or st.session_state.get('alert_check_busy', False),
               on_click=queue_alert_check, type='primary', width='stretch',
               help='Chạy kiểm tra và cập nhật lại danh sách công việc.')
    if st.session_state.pop('alert_check_pending', False):
        try:
            with st.spinner('Đang kiểm tra công việc và cảnh báo...'):
                run_workflow_b()
                # Acknowledgement may precede completion; poll at most 3 times.
                for _ in range(3):
                    time.sleep(0.75)
                    latest = service.snapshot(include_clock=True)
                st.session_state.alert_check_snapshot = latest
            st.session_state.alert_check_result = ('success', 'Đã chạy kiểm tra cảnh báo.')
        except WorkflowRunError as error:
            st.session_state.alert_check_result = ('warning', str(error))
        except DatabaseError:
            st.session_state.alert_check_result = ('warning',
                'Đã gửi yêu cầu kiểm tra nhưng chưa đọc lại được dữ liệu. Vui lòng làm mới danh sách.')
        finally:
            st.session_state.alert_check_busy = False
        st.rerun()
    result = st.session_state.pop('alert_check_result', None)
    if result:
        getattr(st, result[0])(result[1])
        if result[0] == 'success':
            st.caption('Hệ thống có thể vẫn đang xử lý. Nếu chưa thấy thay đổi, hãy làm mới danh sách sau ít giây.')
    reminder_result = st.session_state.pop('reminder_result', None)
    if reminder_result:
        getattr(st, reminder_result[0])(reminder_result[1])
    notice = st.session_state.pop('db_status_notice', None)
    if notice:
        st.success(notice)
    try:
        snapshot = st.session_state.pop('alert_check_snapshot', None)
        tasks, employees, clock = snapshot if snapshot is not None else service.snapshot(include_clock=True)
    except DatabaseError:
        st.error('Không thể tải công việc. Vui lòng kiểm tra kết nối và làm mới.')
        return
    tasks = [t for t in tasks if t['status'] in LABELS]
    alerts = {t['task_id']: t['alert_groups'] for t in attention_tasks(tasks, clock['today'])}
    tasks = [dict(t, alert_groups=alerts.get(t['task_id'], [])) for t in tasks]
    timestamp.caption(f"Cập nhật lúc: {clock['read_at'].strftime('%H:%M:%S %d/%m/%Y')}")
    counters = [('Tổng số task', len(tasks))]
    counters += [(ALERT_LABELS[g], sum(g in t['alert_groups'] for t in tasks))
                 for g in ('due_soon', 'overdue', 'blocked')]
    for col, (label, count), name in zip(st.columns(4), counters,
                                        ('total','due_soon','overdue','blocked')):
        with col.container(key=f'summary_{name}'):
            st.metric(label, count)
    for key, options in (('db_status', LABELS), ('db_alert_group', ALERT_LABELS)):
        if st.session_state.get(key) is not None and st.session_state[key] not in options:
            st.session_state[key] = None
    with st.container(key='task_filters'):
        heading, reset = st.columns([4, 1], vertical_alignment='center')
        heading.markdown('<span class="task-filter-title">Bộ lọc</span>', unsafe_allow_html=True)
        reset.button('Xóa bộ lọc', on_click=clear_filters, key='clear_task_filters')
        a, b, c, d, e = st.columns([1, 1.2, 1, 1, 1.5], gap='small')
        status = a.selectbox('Trạng thái', [None, *LABELS],
                             format_func=lambda v: LABELS.get(v, 'Tất cả'), key='db_status')
        owner = b.selectbox('Người phụ trách', [None, *sorted({o for t in tasks for o in t['owners']})],
                            format_func=lambda v: 'Tất cả' if v is None else
                            f'{v} · {employees[v]}' if v in employees else v, key='db_owner')
        group = c.selectbox('Loại cảnh báo', [None, *ALERT_LABELS],
                            format_func=lambda v: ALERT_LABELS.get(v, 'Tất cả'), key='db_alert_group')
        meeting = d.selectbox('Cuộc họp', [None, *sorted({t['meeting_id'] for t in tasks
                                                        if t['meeting_id'] is not None})],
                              format_func=lambda v: 'Tất cả' if v is None else v,
                              key='db_meeting')
        search = e.text_input('Tìm kiếm', key='db_search',
                              placeholder='Tìm theo mã hoặc mô tả công việc',
                              icon=':material/search:')
    filtered = filter_tasks(tasks, status, owner, meeting, search)
    if group is not None:
        filtered = [t for t in filtered if group in t['alert_groups']]
    if not filtered:
        st.info('Không có công việc phù hợp. Kiểm tra bộ lọc hoặc làm mới để xem công việc mới.')
        return

    def owners(task):
        return owner_text(task, employees)

    st.html(task_table(filtered, owners, clock['today']))
    for task in filtered:
        with st.expander(f"{task_code(task)} · {task['description']}"):
            info, deps, reminders = st.columns(3)
            with info.container(key=f"detail_info_{task['task_id']}"):
                st.markdown('#### ◇ Thông tin công việc')
                st.text(task_code(task))
                st.text(task['description'])
                st.text(f"Người phụ trách: {owners(task)}")
                deadline_kind = next((g for g in ('overdue', 'due_soon')
                                      if g in task['alert_groups']), 'ready')
                st.markdown(badge('Hạn hoàn thành: ' + deadline_text(task['deadline']),
                                  deadline_kind), unsafe_allow_html=True)
                st.markdown(badge(LABELS.get(task['status'], task['status']), task['status']), unsafe_allow_html=True)
                st.caption(f"Ngày tạo: {task.get('created_at') or 'Chưa có dữ liệu'}")
                st.caption(f"Cập nhật gần nhất: {task['updated_at']}")
            with deps.container(key=f"detail_deps_{task['task_id']}"):
                if task.get('dependencies'):
                    dependency_details(task, owners, today=clock['today'])
                else:
                    st.markdown('#### ⤷ Công việc tiền đề')
                    st.caption('Không có công việc tiền đề')
            with reminders.container(key=f"detail_reminders_{task['task_id']}"):
                st.markdown('#### ◷ Nhắc nhở')
                reminded = task.get('last_reminded_at')
                st.caption(f"Lần nhắc gần nhất: {reminded.strftime('%H:%M:%S %d/%m/%Y')}"
                           if reminded else 'Chưa gửi nhắc nhở')
                reminder_button(task['task_id'])
            choices = TRANSITIONS.get(task['status'], ())
            if not choices:
                continue
            with st.form(f"db_update_{task['task_id']}"):
                after = st.selectbox('Cập nhật trạng thái', choices,
                                     format_func=LABELS.get)
                if st.form_submit_button('Lưu trạng thái'):
                    try:
                        service.update_status(task['task_id'], task['status'], after)
                    except DatabaseError as error:
                        st.error(str(error))
                    else:
                        st.session_state.db_status_notice = 'Đã cập nhật trạng thái công việc.'
                        st.rerun()
