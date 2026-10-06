from datetime import date
from .formatters import value_text, label as format_label, task_code, STATUS_LABELS, CONTENT_TYPE_LABELS, DECISION_LABELS, COMMITMENT_LABELS
import streamlit as st
from .components import decision_badge, empty_state
from .review_state import refresh_reviewed_json
from services.review_service import missing_task_owner, OWNER_REQUIRED_MESSAGE


def banner():
    st.caption('Chế độ staging — Thao tác chỉ được lưu trong phiên hiện tại.')
    st.caption('Chưa tích hợp — Chức năng này sẽ được kết nối qua n8n ở giai đoạn tiếp theo.')


def edit_form(key, item, label, save):
    item = dict(item, **item.get('draft', {}))
    with st.form(key):
        description = st.text_area('Mô tả', value=value_text(item.get('description'), ''))
        owners = st.text_input('Người phụ trách (phân tách bằng dấu phẩy)', value=value_text(item.get('owners'), ''))
        try:
            initial = date.fromisoformat(item['deadline']) if item.get('deadline') else None
        except (ValueError, TypeError):
            initial = None
        deadline = st.date_input('Hạn hoàn thành', value=initial)
        if st.form_submit_button(label):
            try:
                save(dict(description=description, owners=owners.split(','),
                          deadline=deadline.isoformat() if deadline else None))
            except ValueError as error:
                st.error(str(error))
            else:
                st.rerun()


def review_screen(service, submit=None):
    def decide(key, action, changes=None):
        try:
            service.decide(key, action, changes)
        finally:
            st.session_state['item_validation_errors'] = {
                i['item_id']: i['validation_errors'] for i in service.store['items'].values()
                if i.get('validation_errors') and i.get('review_status') != 'rejected'}
        refresh_reviewed_json(st.session_state)

    st.subheader('Xác nhận thủ công')
    st.caption('Xử lý từng item trước khi xác nhận và gửi toàn bộ batch.')
    from .manual_tasks import manual_tasks
    manual_tasks(service)
    if submit:
        submit()
    pending = service.pending()
    a, b = st.columns(2)
    a.metric('Items to review', len(pending))
    b.metric('Reviewed today (UTC)', service.reviewed_today())
    if not pending:
        empty_state('✓', 'Không có item chờ review', 'Mở Transcript và chạy extraction để nạp kết quả mới.')
        return
    for item in pending:
        key = item['task_id']
        with st.expander(f"{item['meeting_id']} · {item['item_id']} · {item['description']}", expanded=bool(item.get("validation_errors"))):
            st.caption('AI · Trích xuất từ biên bản')
            item_card(item)
            for error in item.get('validation_errors', []):
                st.error(error)
            audit = (st.session_state.get('extraction_audit') or {}).get('items', {}).get(item['item_id'], {})
            if audit.get('source_validation_status') == 'mismatch':
                st.warning('Trích dẫn của model không khớp transcript. Vui lòng kiểm tra lại nội dung công việc trước khi xác nhận.')
            owner_missing = missing_task_owner(item)
            chosen_owners = []
            if owner_missing:
                owner_text = st.text_input('Người phụ trách cần xác nhận (phân tách bằng dấu phẩy)',
                                           key=f'required_owner:{key}')
                chosen_owners = [owner.strip() for owner in owner_text.split(',') if owner.strip()]
                st.caption(OWNER_REQUIRED_MESSAGE)
            a, b = st.columns(2)
            if a.button('Xác nhận', key=f'confirm:{key}', disabled=owner_missing and not chosen_owners):
                try:
                    if owner_missing:
                        decide(key, 'edit', dict(description=item['description'], owners=chosen_owners,
                                                deadline=item.get('deadline')))
                    else:
                        decide(key, 'confirm')
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.rerun()
            if b.button('Bỏ item', key=f'reject:{key}'):
                decide(key, 'reject'); st.rerun()
            with st.expander('Chỉnh sửa', expanded=bool(item.get('validation_errors'))):
                edit_form(f'review_edit:{key}', item, 'Lưu và xác nhận',
                          lambda changes, key=key: decide(key, 'edit', changes))


def item_card(item):
    """Presentation only; never updates the extraction snapshot."""
    card_key = f"{item.get('meeting_id', '')}_{item.get('item_id', '')}"
    decision_badge(item.get('expected_decision'))
    with st.container(key=f'item_description_{card_key}'):
        st.text(value_text(item.get('description')))
    fields = [('Mã item', value_text(item.get('item_id'))),
              ('Người phụ trách', value_text(item.get('owners'), 'Chưa phân công')),
              ('Hạn hoàn thành', value_text(item.get('deadline'), 'Chưa xác định')),
              ('Loại nội dung', format_label(item.get('content_type'), CONTENT_TYPE_LABELS)),
              ('Mức độ cam kết', format_label(item.get('commitment'), COMMITMENT_LABELS)),
              ('Phụ thuộc', value_text(item.get('depends_on')))]
    with st.container(key=f'item_metadata_{card_key}'):
        for offset in range(0, len(fields), 3):
            for column, (heading, value) in zip(st.columns(3), fields[offset:offset + 3]):
                column.caption(heading)
                column.text(value)
    for key, heading, value in (
        ('item_evidence', 'Trích dẫn cuộc họp', value_text(item.get('source_excerpt'))),
        ('item_review_reason', 'Lý do cần kiểm tra', value_text(item.get('review_reason'))),
    ):
        with st.container(key=f'{key}_{card_key}'):
            st.caption(heading)
            st.text(value)
