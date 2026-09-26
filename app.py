"""Streamlit presentation layer for the shared transcript pipeline."""
import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import config
import requests
from services.n8n_service import N8N_WEBHOOK_URL, send_to_n8n
from services.store import new_store, sync_meeting
from services.review_service import ReviewService
from services.task_service import TaskService
from services.monitoring_service import MonitoringService
from src.request_context import gemini_request
from ui import staging, demo
from ui.components import empty_state
from ui.review_state import refresh_reviewed_json
from ui.operations import review_screen, dashboard, task_detail, monitoring, item_card
from ui.formatters import CONTENT_TYPE_LABELS, value_text, label as format_label

import streamlit as st
from pydantic import ValidationError

from run import transcript_metadata
from src.pipeline import DailyQuotaExceededError, PipelineError, process_transcript
from src.schema_validator import OutputValidationError

STAGES = ("LLM Extraction", "Schema Validation", "Business Validation", "Decision Policy")
TABLE_FIELDS = ("item_id", "content_type", "description", "owners", "deadline",
                "commitment", "depends_on", "expected_decision")
DECISION_COLORS = {"confirmed": "green", "human_review": "orange", "not_task": "gray"}
CSS = """
<style>
.stApp { background: #f5f8fc; color: #172b4d; }
[data-testid="stSidebar"] { background: #fff; border-right: 1px solid #e5eaf1;
    width: 270px !important; min-width: 270px !important; max-width: 85vw; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: 1rem 0.8rem; }
.sidebar-brand { font-size: 1.12rem; font-weight: 700; color: #173d78; margin-bottom: 2px; }
.sidebar-tagline { font-size: .76rem; color: #718096; margin-bottom: 16px; }
.nav-group { font-size: .72rem; color: #718096; font-weight: 600; margin: 12px 0 4px; }
.st-key-sidebar-nav [data-testid="stVerticalBlock"] { gap: .2rem; }
.st-key-sidebar-nav button[kind="secondary"] {
    min-height: 2.25rem; padding: .45rem .6rem; border: 0 !important;
    border-radius: 6px; background: transparent; color: #4a5568;
    justify-content: flex-start; align-items: center; box-shadow: none;
}
.st-key-sidebar-nav button[kind="secondary"]:hover { background: #f0f6fd; color: #174a8b; }
.st-key-sidebar-nav button:focus-visible { outline: 1px solid #2563eb; outline-offset: 2px; }
.task-card { background: white; border: 1px solid #e1e8f2; border-radius: 14px; padding: 24px; margin: 12px 0 24px; overflow-wrap: anywhere; }
.task-description { font-size: 1.4rem; font-weight: 650; color: #173d78; margin-bottom: 16px; white-space: pre-wrap; }
.task-badges { display: flex; gap: 8px; flex-wrap: wrap; }
.task-badge { background: #edf4ff; color: #174a8b; border-radius: 20px; padding: 5px 10px; font-size: .8rem; }
.task-badge.green { background: #eaf7ef; color: #166534; }
.task-badge.orange { background: #fff4df; color: #92400e; }
.task-badge.gray { background: #f1f5f9; color: #475569; }
.task-badge.red { background: #fff0f0; color: #b91c1c; }
@media (max-width: 640px) { .task-card { padding: 16px; } .task-description { font-size: 1.15rem; } }
[data-testid="stHeader"] { background: #f5f8fc; }
[data-testid="stMetric"], [data-testid="stExpander"] {
    background: #fff; border: 1px solid #e1e8f2; border-radius: 14px; padding: 16px;
}
[data-testid="stMetric"] { border-top: 3px solid #3b82f6; }
h1, h2, h3 { color: #173d78; }
button[kind="primary"] { background: #2563eb; border-color: #2563eb; border-radius: 9px; }
[data-baseweb="tab"][aria-selected="true"] { color: #2563eb; }
[data-baseweb="tab-highlight"] { background-color: #2563eb; }
[data-baseweb="tab-list"] { gap: 20px; }
.st-key-metric_confirmed [data-testid="stMetric"] { border-top-color: #16a34a; }
.st-key-metric_human_review [data-testid="stMetric"] { border-top-color: #d97706; }
.st-key-metric_not_task [data-testid="stMetric"] { border-top-color: #64748b; }
.stMainBlockContainer { padding-top: 1.8rem; padding-bottom: 2rem; }
[data-testid="stVerticalBlock"] { gap: .65rem; }
h1 { font-size: 1.85rem !important; letter-spacing: -.025em; padding-bottom: .3rem !important; }
h2 { font-size: 1.3rem !important; }
h3 { font-size: 1.12rem !important; padding-top: .45rem !important; }
[data-testid="stCaptionContainer"] { color: #62748b; }
[data-testid="stMetric"] { padding: 12px 16px; border-radius: 10px; }
[data-testid="stMetricValue"] { font-size: 1.75rem; font-weight: 650; }
[data-testid="stMetricLabel"]::before { content: '◈'; color: #64748b; margin-right: .4rem; }
.st-key-metric_confirmed [data-testid="stMetricLabel"]::before { content: '✓'; color: #166534; }
.st-key-metric_human_review [data-testid="stMetricLabel"]::before { content: '◷'; color: #92400e; }
.st-key-metric_not_task [data-testid="stMetricLabel"]::before { content: '−'; }
[data-testid="stExpander"] { padding: 2px 8px; border-radius: 10px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 10px; background: #fff; }
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
[class*="st-key-item_metadata_"] [data-testid="stHorizontalBlock"] {
    background: #f5f8fc; border-radius: 8px; padding: .55rem .75rem;
}
[class*="st-key-item_metadata_"] [data-testid="stVerticalBlock"] { gap: .15rem; }
[class*="st-key-item_description_"] [data-testid="stText"] { font-size: 1.04rem; font-weight: 600; color: #173d78; }
[class*="st-key-item_evidence_"] { border-left: 3px solid #d6e4f5; padding-left: .8rem; }
[class*="st-key-item_review_reason_"] { border-top: 1px solid #e5eaf1; padding-top: .45rem; }
.task-card { padding: 18px; margin: 8px 0 16px; border-radius: 10px; }
.task-description { font-size: 1.2rem; margin-bottom: 12px; }
.sidebar-tagline { margin-bottom: 10px; }
.nav-group { border-top: 1px solid #e5eaf1; padding-top: 10px; margin: 8px 0 3px; letter-spacing: .025em; }
.st-key-sidebar-nav button[kind="secondary"] { min-height: 2rem; padding: .35rem .6rem; }
.empty-state { text-align: center; padding: 1.6rem 1rem; border: 1px dashed #cedbea;
    border-radius: 12px; background: #fff; color: #173d78; }
.empty-icon { font-size: 1.65rem; color: #5479a8; margin-bottom: .35rem; }
.empty-state p { color: #62748b; font-size: .9rem; margin: .4rem 0 0; }
</style>
"""


def item_counts(items):
    """Count existing policy labels for presentation only."""
    return {decision: sum(item["expected_decision"] == decision for item in items)
            for decision in DECISION_COLORS}


def display_value(value):
    if value is None or value == [] or value == {} or (isinstance(value, str) and not value.strip()):
        return "—"
    if isinstance(value, list):
        return ", ".join(str(entry) for entry in value)
    return str(value)


def friendly_error_message(error):
    """Translate exceptions for display only; never retry or alter validation."""
    chain = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        chain.append(error)
        error = error.__cause__
    if any(isinstance(exc, DailyQuotaExceededError) for exc in chain):
        return "Đã đạt giới hạn sử dụng API hôm nay. Vui lòng thử lại sau khi quota được reset hoặc kiểm tra API plan."
    if any(isinstance(exc, (OutputValidationError, ValidationError, json.JSONDecodeError))
           for exc in chain):
        return "Kết quả LLM không hợp lệ theo schema hoặc business rules. Vui lòng xem chi tiết ở tab Validation & JSON."
    if any(isinstance(exc, TimeoutError) or 'timeout' in type(exc).__name__.lower() for exc in chain):
        return 'Dịch vụ AI phản hồi quá lâu. Vui lòng thử lại sau.'
    if any('Session Gemini call limit reached' in str(exc) for exc in chain):
        return 'Đã đạt giới hạn gọi Gemini trong phiên hiện tại.'
    for exc in chain:
        status = str(getattr(exc, "code", None) or getattr(exc, "status_code", None))
        detail = str(exc).upper()
        if status == "429" or re.search(r"\b(?:429|RESOURCE_EXHAUSTED)\b", detail):
            return "Đã đạt giới hạn sử dụng API hiện tại. Vui lòng thử lại sau hoặc kiểm tra quota/API plan."
        if status == "503" or re.search(r"\b(?:503|UNAVAILABLE)\b", detail):
            return "Dịch vụ AI đang tạm thời quá tải. Vui lòng thử lại sau ít phút."
    return "Đã xảy ra lỗi khi xử lý transcript. Vui lòng thử lại hoặc xem chi tiết trong Logs."


def clear_result():
    for key in ("raw_output", "validated_object", "final_object", "final_json", "reviewed_json", "error_message", "user_error_message", "result_input"):
        st.session_state[key] = None
    st.session_state.pipeline_status = dict.fromkeys(STAGES, "Chưa chạy")


def failure_status(failure):
    """Present completed stages from pipeline errors, without revalidating data."""
    status = dict.fromkeys(STAGES, "Chưa chạy")
    if failure.raw_output is None:
        status[STAGES[0]] = "Thất bại"
    else:
        status[STAGES[0]] = "Thành công"
        if failure.validated_object is not None:
            status.update({STAGES[1]: "Thành công", STAGES[2]: "Thành công", STAGES[3]: "Thất bại"})
        elif isinstance(failure.error, OutputValidationError):
            cause = failure.error.__cause__
            if isinstance(cause, json.JSONDecodeError):
                status[STAGES[1]] = "Không chạy: JSON không hợp lệ"
            elif isinstance(cause, ValidationError):
                status[STAGES[1]] = "Thất bại"
            else:
                status[STAGES[1]] = "Thành công"
                status[STAGES[2]] = "Thất bại"
        else:
            status[STAGES[1]] = "Không hoàn tất"
    return status


def extract(transcript, meeting_id, meeting_date, evidence):
    settings = staging.read_settings()
    staging.require_login(settings)
    staging.init_usage()
    if st.session_state.extraction_count >= config.MAX_EXTRACTIONS_PER_SESSION:
        st.warning('Đã đạt giới hạn extraction trong phiên hiện tại.')
        return
    lock = st.session_state.extraction_lock
    if not lock.acquire(blocking=False):
        st.info('Đang xử lý transcript. Vui lòng đợi kết quả.')
        return
    st.session_state.extraction_busy = True
    st.session_state.extraction_count += 1
    if st.session_state.get('data_source') == 'demo':
        st.session_state.demo_store = new_store()
    st.session_state.data_source = 'extraction'
    clear_result()
    st.session_state.result_input = (transcript, meeting_id, meeting_date, evidence)
    try:
        with gemini_request(staging.request_context(settings)):
            raw, validated, final = process_transcript(transcript, meeting_id, meeting_date, evidence)
    except PipelineError as failure:
        st.session_state.raw_output = failure.raw_output
        st.session_state.validated_object = failure.validated_object
        st.session_state.pipeline_status = failure_status(failure)
        st.session_state.error_message = staging.redact_error(failure.error, settings)
        st.session_state.user_error_message = friendly_error_message(failure.error)
    except Exception as error:
        st.session_state.error_message = staging.redact_error(error, settings)
        st.session_state.user_error_message = friendly_error_message(error)
        st.session_state.pipeline_status[STAGES[0]] = "Không hoàn tất"
    else:
        st.session_state.raw_output = raw
        st.session_state.validated_object = validated
        st.session_state.final_object = final
        if 'demo_store' in st.session_state:
            st.session_state.demo_store['versions'].pop(staging.as_dict(final)['meeting_id'], None)
            sync_meeting(st.session_state.demo_store, final)
        refresh_reviewed_json(st.session_state)
        st.session_state.pipeline_status = dict.fromkeys(STAGES, "Thành công")

    finally:
        st.session_state.extraction_busy = False
        lock.release()


def remember_upload():
    st.session_state.saved_upload = st.session_state.get('transcript_upload')


def render_transcript():
    st.subheader("Transcript input")
    st.caption("Hoạt động — Gemini chỉ được gọi khi bấm Run Extraction.")
    left, right = st.columns([1, 2], gap="large")
    with left:
        uploaded = st.file_uploader("Upload transcript (.txt)", type=["txt"],
                                    key="transcript_upload", on_change=remember_upload)
        if uploaded is not None:
            st.session_state.saved_upload = uploaded
        else:
            uploaded = st.session_state.get("saved_upload")
        transcript = ""
        input_error = None
        if uploaded is not None:
            try:
                transcript = staging.upload_text(uploaded)
            except ValueError as error:
                input_error = str(error)
        if uploaded is not None:
            st.caption(f'{uploaded.name} · {len(uploaded.getvalue()):,} bytes · {len(transcript.splitlines())} dòng')
        if st.session_state.get('data_source') != 'demo':
            st.session_state.transcript = transcript
        identity = (uploaded.name, uploaded.getvalue()) if uploaded is not None else None
        if identity != st.session_state.get("upload_identity"):
            st.session_state.upload_identity = identity
            clear_result()
            if st.session_state.get('data_source') == 'demo':
                st.session_state.demo_store = new_store()
                st.session_state.data_source = 'extraction'
                st.info('Đã thay dữ liệu minh họa bằng transcript mới.')
            st.session_state.meeting_id = Path(uploaded.name).stem if uploaded else ""
            st.session_state.meeting_date = None
            st.session_state.metadata_error = None
            if transcript.strip():
                try:
                    day, _ = transcript_metadata(transcript)
                    st.session_state.meeting_date = date.fromisoformat(day) if day else None
                except (ValueError, argparse.ArgumentTypeError) as error:
                    st.session_state.metadata_error = str(error)
        meeting_id = st.text_input("Meeting ID", key="meeting_id", placeholder="M001")
        meeting_date = st.date_input("Meeting Date", value=None, key="meeting_date",
                                     help="Để trống nếu chưa xác định được ngày họp.")
        if st.session_state.get("metadata_error"):
            st.warning("Dòng ngày họp không hợp lệ. Kiểm tra và chọn Meeting Date trước khi chạy.")
        if input_error:
            st.error(input_error)
        if uploaded is not None and not transcript.strip() and not input_error:
            st.warning("Transcript không được để trống.")
        day = meeting_date.isoformat() if meeting_date else None
        current_input = (transcript, meeting_id.strip(), day, None)
        if st.session_state.result_input is not None and st.session_state.result_input != current_input:
            clear_result()
        exhausted = st.session_state.extraction_count >= config.MAX_EXTRACTIONS_PER_SESSION
        if exhausted:
            st.warning('Đã đạt giới hạn extraction trong phiên hiện tại.')
        if st.button("Run Extraction", type="primary", disabled=(
                exhausted or st.session_state.extraction_busy or
                not transcript.strip() or not meeting_id.strip() or input_error is not None),
                width="stretch"):
            with st.spinner("Đang trích xuất và kiểm tra kết quả…"):
                extract(*current_input)
        if st.session_state.error_message:
            st.error(st.session_state.get("user_error_message") or friendly_error_message(None))
        elif st.session_state.final_object is not None and st.session_state.get("data_source") != "demo":
            st.success("Extraction thành công. Xem Extraction Result và Validation & JSON.")
            items = staging.as_dict(st.session_state.final_object)["items"]
            counts = item_counts(items)
            st.caption(
                f"Total Items: {len(items)} · confirmed: {counts['confirmed']} · "
                f"human_review: {counts['human_review']} · not_task: {counts['not_task']}"
            )
    with right:
        st.markdown("**Transcript preview**")
        if transcript:
            with st.container(height=400):
                st.code(transcript, language=None, wrap_lines=True)
        else:
            empty_state('↥', 'Chưa có transcript', 'Chọn Upload transcript (.txt) ở bên trái để bắt đầu.')


def render_results():
    st.subheader("Extraction result")
    final = st.session_state.get('reviewed_json')
    if final is None:
        final = st.session_state.get('final_json')
    if final is None:
        empty_state('▤', 'Chưa có kết quả extraction', 'Mở Transcript, tải file .txt và bấm Run Extraction.')
        return
    final = staging.as_dict(final)
    if st.session_state.get('reviewed_json') is not None:
        st.caption('Đã cập nhật sau Human Review — kết quả hiển thị và JSON gửi n8n bao gồm các thay đổi đã duyệt.')
    if st.button("Send to Task Workflow", key="send_to_task_workflow"):
        try:
            with st.spinner("Đang gửi dữ liệu sang n8n…"):
                # Temporary debug display: the same URL used by the POST service.
                st.text(f"DEBUG n8n POST URL: {N8N_WEBHOOK_URL}")
                response = send_to_n8n(final)
        except requests.HTTPError as error:
            st.error(f"n8n trả về lỗi HTTP {error.response.status_code}.")
            st.text(error.response.text)
        except requests.Timeout:
            st.error("n8n không phản hồi trong thời gian chờ. Hãy kiểm tra workflow trước khi gửi lại.")
        except requests.ConnectionError:
            st.error("Không kết nối được n8n. Vui lòng kiểm tra n8n đang chạy tại localhost:5678 và webhook đang lắng nghe.")
        except requests.RequestException:
            st.error("Không thể gửi dữ liệu sang n8n. Vui lòng kiểm tra kết nối và workflow.")
        else:
            if 200 <= response.status_code < 300:
                st.success("Đã gửi dữ liệu sang n8n thành công.")
            else:
                st.error(f"n8n trả về HTTP {response.status_code}.")
                st.text(response.text)
    items = final["items"]
    counts = item_counts(items)
    columns = st.columns(4)
    columns[0].metric("Total Items", len(items))
    for column, label, decision in zip(columns[1:], ("Confirmed", "Human Review", "Not Task"), DECISION_COLORS):
        with column:
            with st.container(key=f"metric_{decision}"):
                st.metric(label, counts[decision])
    st.caption(f"Meeting: {final.get('meeting_id')} · Date: {final.get('meeting_date') or 'Chưa xác định'}")
    selected = st.selectbox('Loại nội dung', ['all', 'task_candidate', 'information', 'decision', 'proposal'],
                            format_func=lambda v: 'Tất cả' if v == 'all' else format_label(v, CONTENT_TYPE_LABELS))
    visible = [item for item in items if selected == 'all' or item.get('content_type') == selected]
    # Restore the column-oriented summary from a6fac57, using the filtered items.
    table = {field: [value_text(item.get(field), '-') for item in visible]
             for field in TABLE_FIELDS}
    headings = ('Item ID', 'Content Type', 'Description / Task', 'Owner(s)',
                'Deadline', 'Commitment', 'Depends On', 'Decision / Status')
    # Reset row positions when the filter or extraction changes.
    snapshot = json.dumps([selected, final], sort_keys=True, ensure_ascii=False)
    table_key = 'extraction_summary_' + hashlib.sha256(snapshot.encode()).hexdigest()[:16]
    event = st.dataframe(
        table, width='stretch', hide_index=True, row_height=38,
        column_config=dict(zip(TABLE_FIELDS, headings)),
        on_select='rerun', selection_mode='single-row', key=table_key)
    if not visible:
        empty_state('⌕', 'Không có item phù hợp với bộ lọc.', 'Chọn Tất cả trong Loại nội dung để xem các item còn lại.')
        return
    st.caption('Chọn một hàng để đưa chi tiết item đó lên đầu phần bên dưới.')
    selected_rows = event.selection.rows
    selected_index = selected_rows[0] if selected_rows else None
    order = list(range(len(visible)))
    if isinstance(selected_index, int) and selected_index in order:
        order.remove(selected_index)
        order.insert(0, selected_index)
    st.subheader('Chi tiết item')
    for index in order:
        with st.container(border=True):
            if index == selected_index:
                st.caption('Item đang chọn')
            item_card(visible[index])


def render_validation():
    st.subheader("Validation & JSON")
    stages = dict(st.session_state.pipeline_status)
    raw = st.session_state.raw_output
    parse_status = 'Chưa chạy'
    if raw is not None and st.session_state.get('data_source') != 'demo':
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else staging.as_dict(raw)
            parse_status = 'Thành công'
        except (ValueError, TypeError):
            parse_status = 'Thất bại'
    stages = {STAGES[0]: stages[STAGES[0]], 'Parse JSON': parse_status, **{k: stages[k] for k in STAGES[1:]}}
    stages = {stage: status if status in ('Thành công', 'Thất bại', 'Chưa chạy') else ('Chưa chạy' if status.startswith('Không chạy') else 'Thất bại') for stage, status in stages.items()}
    for column, stage in zip(st.columns(5), stages):
        with column:
            st.markdown(f"**{stage}**")
            status = stages[stage]
            if status == "Thành công":
                st.success(status)
            elif status in ("Thất bại", "Không hoàn tất"):
                st.error(status)
            else:
                st.info(status)
    if st.session_state.error_message:
        st.error(st.session_state.get("user_error_message") or friendly_error_message(None))
    raw_tab, validated_tab, final_tab, logs_tab = st.tabs(
        ["Raw JSON", "Validated Object", "Final JSON", "Logs"])
    for tab, key in zip((raw_tab, validated_tab, final_tab),
                        ("raw_output", "validated_object", "final_object")):
        with tab:
            st.markdown(f"**{key}**")
            value = st.session_state[key]
            if value is None:
                st.caption("Chưa có dữ liệu.")
            elif key == "raw_output":
                try:
                    st.json(json.loads(value) if isinstance(value, str) else staging.as_dict(value))
                except (json.JSONDecodeError, TypeError):
                    st.warning("Raw output không phải JSON hợp lệ.")
                    st.code(value, language=None, wrap_lines=True)
                with st.expander("Raw output nguyên văn"):
                    st.code(value, language=None, wrap_lines=True)
            else:
                st.json(staging.as_dict(value))
            if value is not None and key in ('raw_output', 'final_object'):
                kind = 'raw' if key == 'raw_output' else 'final'
                try:
                    data = staging.json_download(value)
                except (ValueError, TypeError):
                    st.caption('Raw không phải JSON hợp lệ; xem nội dung nguyên văn ở trên.')
                else:
                    meeting_id = (st.session_state.result_input or ('', staging.as_dict(st.session_state.final_object).get('meeting_id', 'meeting') if st.session_state.final_object is not None else 'meeting'))[1]
                    st.download_button(f"Download {'Raw' if kind == 'raw' else 'Final'} JSON", data=data,
                                       file_name=staging.download_name(meeting_id, kind),
                                       mime='application/json', on_click='ignore', key=f'download_{kind}')
    with logs_tab:
        for stage in stages:
            st.markdown(f"**{stage} status**")
            st.text(stages[stage])
        if st.session_state.error_message:
            st.error(st.session_state.error_message)
        else:
            st.caption("Không có lỗi được ghi nhận.")
        with st.expander('Sử dụng API trong phiên'):
            st.text(f'Extraction: {st.session_state.extraction_count} / {config.MAX_EXTRACTIONS_PER_SESSION}\n'
                    f'Lần gọi Gemini (gồm retry): {st.session_state.gemini_call_count}')
            if st.session_state.usage_history:
                st.json(st.session_state.usage_history)
            st.caption('Token fields chỉ hiển thị khi SDK cung cấp; không ước lượng dữ liệu thiếu.')


def main():
    st.set_page_config(page_title="Meeting Task Extractor", page_icon="📝", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    try:
        settings = staging.read_settings()
    except Exception:
        st.error('Không đọc được cấu hình Secrets. Hãy kiểm tra định dạng TOML.')
        st.stop()
    staging.require_login(settings)
    staging.init_usage()
    if "pipeline_status" not in st.session_state:
        if st.session_state.get('data_source') == 'demo':
            st.session_state.pipeline_status = dict.fromkeys(STAGES, 'Chưa chạy')
        else:
            clear_result()
    st.title("Meeting Task Extractor")
    st.caption("LLM & Agent Logic Dashboard")
    st.caption('Chế độ staging — Dữ liệu chỉ tồn tại trong phiên hiện tại; chưa gửi email hoặc tạo lịch.')
    if st.session_state.get('data_source') == 'demo':
        st.info('Dữ liệu minh họa — Không phải kết quả gọi Gemini; các bước validation chưa chạy.')
    # Preserve editable metadata while its widgets are not on the active screen.
    for key in ("meeting_id", "meeting_date"):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    screens = {"Transcript": render_transcript, "Extraction Result": render_results,
               "Validation & JSON": render_validation}
    if config.ENABLE_HUMAN_REVIEW:
        screens["Human Review"] = None
    if config.ENABLE_TASK_DASHBOARD:
        screens["Task Dashboard"] = None
    if config.ENABLE_MONITORING:
        screens["Monitoring & Alerts"] = None
    if "navigate_to" in st.session_state:
        st.session_state.screen = st.session_state.pop("navigate_to")
    if st.session_state.get("screen") not in screens:
        st.session_state.screen = "Transcript"
    if not config.ENABLE_TASK_DASHBOARD:
        st.session_state.selected_task = None
    with st.sidebar:
        st.markdown('<div class="sidebar-brand">Meeting Agent</div><div class="sidebar-tagline">From meetings to actions</div>', unsafe_allow_html=True)
        navigation = [
            ("Transcript", "Transcript", ":material/description:"),
            ("Extraction Result", "Kết quả trích xuất", ":material/analytics:"),
            ("Validation & JSON", "Kiểm tra JSON", ":material/data_object:"),
            ("Human Review", "Xác nhận thủ công", ":material/rate_review:"),
            ("Task Dashboard", "Danh sách công việc", ":material/task_alt:"),
            ("Monitoring & Alerts", "Theo dõi & cảnh báo", ":material/monitoring:"),
        ]
        with st.container(key="sidebar-nav"):
            for title, entries in (("Xử lý cuộc họp", navigation[:3]), ("Quản lý công việc", navigation[3:])):
                visible = [entry for entry in entries if entry[0] in screens]
                if not visible:
                    continue
                st.markdown(f'<div class="nav-group">{title}</div>', unsafe_allow_html=True)
                for route, caption, icon in visible:
                    slug = route.lower().replace(' ', '-').replace('&', 'and')
                    with st.container(key=f"nav-item-{slug}"):
                        if st.button(caption, icon=icon, key=f"nav_{route}", width="stretch"):
                            st.session_state.screen = route
        screen = st.session_state.screen
        active_slug = screen.lower().replace(' ', '-').replace('&', 'and')
        st.markdown(f'''<style>
        .st-key-sidebar-nav .st-key-nav-item-{active_slug} button[kind="secondary"] {{
            background: #eaf3ff; color: #174a8b; font-weight: 650;
            box-shadow: inset 3px 0 #2563eb; border: 0 !important;
        }}
        </style>''', unsafe_allow_html=True)
    with st.sidebar:
        if st.session_state.final_object is None and not st.session_state.get('saved_upload'):
            st.button('Tải dữ liệu demo', on_click=demo.load_demo, args=(st.session_state,))
        with st.expander('Đặt lại phiên demo'):
            confirmed_reset = st.checkbox('Tôi xác nhận xóa dữ liệu phiên', key='confirm_reset')
            st.button('Đặt lại phiên demo', disabled=not confirmed_reset,
                      on_click=demo.reset_session, args=(st.session_state,))
        st.button('Đăng xuất', on_click=staging.logout, key='logout')
    if "demo_store" not in st.session_state:
        st.session_state.demo_store = new_store()
    store = st.session_state.demo_store
    sync_meeting(store, st.session_state.final_object)
    refresh_reviewed_json(st.session_state)
    reviews, tasks = ReviewService(store), TaskService(store)
    if screens[screen] is not None:
        screens[screen]()
    elif screen == "Human Review":
        review_screen(reviews)
    elif screen == "Task Dashboard":
        selected = st.session_state.get("selected_task")
        if selected:
            task_detail(tasks, selected)
        else:
            dashboard(tasks)
    elif screen == "Monitoring & Alerts":
        monitoring(MonitoringService(tasks, reviews), config.ENABLE_TASK_DASHBOARD, config.ENABLE_HUMAN_REVIEW)
    demo.refresh_views(st.session_state)


if __name__ == "__main__":
    main()
