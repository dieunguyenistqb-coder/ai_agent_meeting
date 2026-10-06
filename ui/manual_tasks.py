"""Manual additions to the active review batch; no network side effects."""
from datetime import date
import streamlit as st
from .review_state import refresh_reviewed_json


def added_form(service, meeting_id, items, item=None):
    item = item or {}
    item_id = item.get('item_id')
    with st.form(f'manual_task:{meeting_id}:{item_id or "new"}', clear_on_submit=False):
        description = st.text_area('Nội dung công việc *', value=item.get('description', ''))
        owners = st.text_input('Người phụ trách * (phân tách bằng dấu phẩy)',
                               value=', '.join(item.get('owners', [])))
        deadline = st.date_input('Hạn hoàn thành (tùy chọn)',
                                 value=date.fromisoformat(item['deadline']) if item.get('deadline') else None)
        priorities = [None, 'low', 'medium', 'high']
        priority = st.selectbox('Mức độ ưu tiên', priorities,
            index=priorities.index(item.get('priority')),
            format_func=lambda v: {None:'Chưa xác định','low':'Thấp','medium':'Trung bình','high':'Cao'}[v])
        targets = {i['item_id']: i for i in items if i['item_id'] != item_id
                   and i.get('review_status') != 'rejected' and i['content_type'] == 'task_candidate'}
        # Retain invalidated references visibly until the user removes them.
        options = list(dict.fromkeys([*targets, *item.get('depends_on', [])]))
        dependencies = st.multiselect('Công việc tiền đề', options, default=item.get('depends_on', []),
            format_func=lambda v: f"{v} — {targets[v]['description']}" if v in targets else f'{v} — đã bị bỏ')
        excerpt = st.text_area('Trích dẫn hoặc ghi chú nguồn (tùy chọn)',
                               value='\n'.join(item.get('source_excerpt', [])))
        save = st.form_submit_button('Thêm công việc' if not item_id else 'Lưu chỉnh sửa')
        cancel = st.form_submit_button('Hủy') if not item_id else False
        if cancel:
            st.session_state['open_add_missing_task_form'] = False
            st.rerun()
        if save:
            try:
                service.save_added(meeting_id, dict(description=description, owners=owners.split(','),
                    deadline=deadline.isoformat() if deadline else None, priority=priority,
                    depends_on=dependencies, source_excerpt=[line.strip() for line in excerpt.splitlines() if line.strip()]), item_id)
                refresh_reviewed_json(st.session_state)
            except ValueError as error:
                st.error(str(error))
            else:
                if not item_id:
                    st.session_state['open_add_missing_task_form'] = False
                st.rerun()


def manual_tasks(service):
    final = st.session_state.get('final_object')
    if final is None:
        return
    data = final.model_dump() if hasattr(final, 'model_dump') else final
    meeting_id = data['meeting_id']
    items = [i for i in service.store['items'].values() if i['meeting_id'] == meeting_id]
    if st.button('+ Thêm công việc bị bỏ sót', key='review_add_missing_task'):
        st.session_state['open_add_missing_task_form'] = True
    if st.session_state.get('open_add_missing_task_form', False):
        st.markdown('#### Thêm công việc bị bỏ sót')
        st.caption('Lưu công việc là xác nhận nội dung và người phụ trách. Công việc chỉ được gửi cùng toàn bộ batch khi bạn bấm xác nhận gửi.')
        added_form(service, meeting_id, items)
    for item in items:
        if item.get('item_origin') != 'human_added' or item.get('review_status') == 'rejected':
            continue
        with st.expander(f"{item['item_id']} · {item['description']} · Người dùng bổ sung"):
            st.caption('Người dùng bổ sung · Đã xác nhận')
            added_form(service, meeting_id, items, item)
            if st.button('Bỏ công việc bổ sung', key=f"discard_added:{item['task_id']}"):
                service.discard_added(item['task_id'])
                refresh_reviewed_json(st.session_state)
                st.rerun()
