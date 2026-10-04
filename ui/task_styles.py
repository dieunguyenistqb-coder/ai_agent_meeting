"""Presentation tokens and escaped badge markup for the task workspace."""
from html import escape

TONES = {'ready': 'slate', 'in_progress': 'blue', 'blocked': 'purple',
         'done': 'green', 'due_soon': 'orange', 'overdue': 'red'}


def badge(label, kind):
    tone = TONES.get(kind, 'slate')
    return f'<span class="task-pill tone-{tone}">{escape(str(label))}</span>'


CSS = """
<style>
.st-key-task_workspace {--task-border:#e5e7eb; color:#0f172a;}
.st-key-task_workspace h3 {color:#0f172a; font-weight:600; letter-spacing:-.025em;}
.st-key-task_workspace [data-testid="stVerticalBlock"] {gap: .8rem;}
.st-key-task_workspace [data-testid="stCaptionContainer"] {color:#64748b;}
.st-key-task_workspace button {border-radius:9px; box-shadow:none;}
.st-key-task_workspace button[kind="primary"] {background:#3870ce; border-color:#3870ce;}
.st-key-task_workspace [data-testid="stMetric"] {
 background:#fff; border:1px solid #e5e7eb; border-top:1px solid #e5e7eb;
 border-radius:13px; padding:12px 16px; box-shadow:none; min-height:84px;}
.st-key-task_workspace [data-testid="stMetricValue"] {font-size:1.75rem; line-height:1.2; font-weight:500; color:#0f172a;}
.st-key-task_workspace [data-testid="stMetricLabel"] {font-size:.8rem; color:#64748b;}
.st-key-task_workspace [data-testid="stMetricLabel"]::before {content:'○'; margin-right:7px;}
.st-key-summary_total [data-testid="stMetricLabel"]::before {color:#2563eb;}
.st-key-summary_due_soon [data-testid="stMetricLabel"]::before {color:#d97706;}
.st-key-summary_overdue [data-testid="stMetricLabel"]::before {color:#dc2626;}
.st-key-summary_blocked [data-testid="stMetricLabel"]::before {color:#7c3aed;}
.st-key-task_filters {background:#fff; border:1px solid #e5e7eb; border-radius:13px;
 padding:12px 18px; margin:12px 0 6px;}
.st-key-task_workspace [data-baseweb="select"] > div,
.st-key-task_workspace [data-baseweb="input"] {border-radius:9px; min-height:40px;
 background:#fafbfc; border-color:#e5e7eb;}
.st-key-task_workspace [data-testid="stExpander"] {background:#fafbfc; border:1px solid #e5e7eb;
 border-radius:12px; padding:8px 12px; box-shadow:none;}
.st-key-task_workspace [data-testid="stExpander"] summary {font-size:.88rem;}
.st-key-task_workspace [class*="st-key-detail_"] {background:#fff; border:1px solid #e9edf2;
 border-radius:12px; padding:18px; height:100%;}
.st-key-task_workspace [class*="st-key-detail_"] h4 {font-size:.85rem; font-weight:600; color:#475569;}
.st-key-task_workspace [class*="st-key-detail_"] [data-testid="stText"] {font-size:.85rem; line-height:1.65;}
.st-key-task_workspace [data-testid="stAlert"] {border-radius:10px; font-size:.85rem;}

.st-key-task_header_actions [data-testid="stVerticalBlock"] {gap:6px;}
.st-key-task_header_actions [data-testid="stCaptionContainer"] {text-align:right;}
.st-key-task_header_actions button {height:42px; min-height:42px; padding:0 12px;}
.st-key-task_header_actions button p {font-size:13px; white-space:normal;
 overflow:visible; text-overflow:clip; line-height:1.2;}
.st-key-task_workspace [data-testid="stCaptionContainer"] {color:#536277;}
.st-key-task_workspace [data-testid="stMetricLabel"] {margin-bottom:2px; min-height:20px;}
.st-key-task_filters [data-testid="stVerticalBlock"] {gap:8px;}
.task-filter-title {font-size:14px; font-weight:600; color:#475569;}
.st-key-task_filters [data-testid="stWidgetLabel"] {min-height:20px; margin-bottom:3px;}
.st-key-task_filters [data-testid="stWidgetLabel"] p {font-size:13px; color:#475569;}
.st-key-task_filters [data-baseweb="select"] > div,
.st-key-task_filters [data-baseweb="input"] {height:40px; min-height:40px; border-radius:8px;}
.st-key-task_filters input::placeholder {color:#6b778a; opacity:1;}
.st-key-clear_task_filters button {min-height:32px; padding:4px 10px; font-size:12px;
 border-color:#e5e7eb; background:transparent;}
.meeting-task-list {width:100%; overflow:auto; max-height:560px; background:#fff;
 border:1px solid #e5e7eb; border-radius:12px; margin:8px 0 20px;}
.meeting-task-list table {width:100%; min-width:980px; table-layout:fixed;
 border-collapse:collapse; font-family:inherit; font-size:13px; color:#334155;}
.meeting-task-list th {text-align:left; background:#f8fafc; position:sticky; top:0;
 z-index:1; font-size:11px; font-weight:500; color:#64748b;}
.meeting-task-list td,.meeting-task-list th {padding:17px 14px; border-bottom:1px solid #f0f2f5;
 vertical-align:top; overflow-wrap:anywhere;}
.meeting-task-list tbody tr:hover {background:#fafbfc;}
.meeting-task-list tbody tr:last-child td {border-bottom:0;}
.meeting-task-list .task-code {color:#334b6b; font-weight:600;}
.meeting-task-list small {display:block; font-size:11px; color:#64748b; margin-top:6px;
 white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.task-pill {display:inline-block; border-radius:999px; padding:3px 8px;
 font-size:11px; line-height:1.5; font-weight:500; margin:0 3px 4px 0; max-width:100%;}
.tone-slate {background:#f1f5f9; color:#64748b;}
.tone-blue {background:#eff6ff; color:#2563eb;}
.tone-green {background:#f0fdf4; color:#15803d;}
.tone-orange {background:#fff7ed; color:#b45309;}
.tone-red {background:#fef2f2; color:#b91c1c;}
.tone-purple {background:#f5f3ff; color:#7c3aed;}
.tone-teal {background:#f0fdfa; color:#0f766e;}
.task-dot {display:inline-block; width:5px; height:5px; border-radius:50%;
 margin:0 8px 2px 0; background:currentColor;}
.task-muted {color:#94a3b8;}
.meeting-task-list .deadline-overdue {color:#b91c1c;}
.meeting-task-list .deadline-due_soon {color:#b45309;}
@media(max-width:1100px) {
 .st-key-task_workspace [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
 .st-key-task_workspace [data-testid="stColumn"] {min-width:220px; flex:1 1 220px;}
}
@media(max-width:600px) {
 .st-key-task_workspace [data-testid="stColumn"] {min-width:100%;}
 .st-key-task_filters {padding:12px;}
 .st-key-task_header_actions [data-testid="stCaptionContainer"] {text-align:left;}
}
</style>
"""
