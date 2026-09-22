# PROJECT_CONTEXT.md

## Project
**Xây dựng AI Agent hỗ trợ trích xuất, xác minh và điều phối công việc từ transcript/biên bản cuộc họp sử dụng LLM và n8n**

MVP hiện tại dùng transcript văn bản tiếng Việt, chưa làm Speech-to-Text và chưa fine-tune.

## Kiến trúc
Transcript
→ Preprocessing
→ LLM Structured Extraction
→ Schema Validation
→ Decision Policy
→ Confirmed / Human Review / Not Task
→ Dependency Handling
→ PostgreSQL
→ Email / Calendar / Monitoring

Phân vai:
- LLM = Understand
- Agent Logic = Decide
- n8n = Orchestrate & Execute

LLM không tự quyết định `confirmed`, `human_review`, `not_task`.
Các giá trị này do Decision Policy thêm sau extraction.

## Vai trò Người 2
- LLM structured extraction
- Prompt engineering
- Quản lý version schema
- Quản lý Decision Policy
- Relative date normalization
- Dependency detection
- Schema validation
- Chạy offline bằng API
- So sánh zero-shot vs few-shot
- Sinh predicted JSON
- Đánh giá output LLM so với ground truth
- Thiết kế và chạy E2E test toàn pipeline
- Phân loại lỗi: LLM / Decision Policy / n8n

## Dataset đã chốt
- 100 transcript tiếng Việt
- 15–40 lượt nói mỗi transcript
- Gần daily/stand-up/project coordination meeting
- 1 ground truth JSON / transcript
- Dùng cho test/evaluation, chưa fine-tune
- QC double-annotation khoảng 15 transcript

Bao phủ các case:
explicit, tentative, ambiguous, no owner, no deadline, relative deadline,
ambiguous/conflicting deadline, multiple owners, dependency, proposal,
decision, information, no action item, corrected deadline, repeated task.

Multiple owners:
- "A và B cùng làm" → owners=["A","B"]
- "A hoặc B làm" → owners=[] → human_review

## Metadata chuẩn
{
  "dataset_type": "meeting_transcript_ground_truth",
  "annotation_version": "1.6",
  "language": "vi",
  "meeting_id": "M001",
  "source_file": "transcript_01.txt",
  "meeting_date": "2026-09-01",
  "meeting_date_evidence": null,
  "items": []
}

meeting_date:
- nêu trực tiếp → meeting_date_evidence=null
- suy ra chắc chắn → lưu evidence + reasoning
- không đủ bằng chứng → meeting_date=null, không đoán

## Item schema
{
  "item_id": "ITEM001",
  "source_excerpt": ["Nam: Em sẽ hoàn thành API trước thứ Sáu."],
  "content_type": "task_candidate",
  "description": "Hoàn thành API",
  "owners": ["Nam"],
  "deadline": "2026-09-04",
  "deadline_text": "trước thứ Sáu",
  "deadline_status": "resolved",
  "priority": null,
  "commitment": "explicit",
  "depends_on": [],
  "temporal_warning": null,
  "expected_decision": "confirmed",
  "review_reason": null
}

## Raw vs Final predicted JSON
LLM raw output KHÔNG có:
- expected_decision
- review_reason

Decision Policy thêm 2 field đó vào final predicted JSON.

## Decision Policy
IF content_type = decision OR information → not_task
ELSE IF content_type = proposal → human_review
ELSE IF owners = [] → human_review
ELSE IF commitment != explicit → human_review
ELSE IF deadline_status IN {ambiguous, conflict} → human_review
ELSE → confirmed

Lưu ý:
- missing vẫn có thể confirmed
- resolved_with_warning không tự động review
- date_resolved_time_ambiguous không tự động review
- event_based không tự động review
- confidence không thuộc ground truth và không tham gia Decision Policy

## Human Review
- Yes → Confirmed
- No → Reject + Audit Log
- Edit → user sửa → Confirmed trực tiếp
Không chạy lại Decision Policy sau Edit.

## Dependency runtime
ITEM001=in_progress → ITEM002=blocked
ITEM001=done → ITEM002=ready

Chỉ tạo dependency khi transcript thể hiện rõ.

## Task Store
PostgreSQL.

Không dùng Streamlit trong MVP hiện tại.
Human Review và cập nhật status dùng n8n Form.

Task status enum:
not_started | in_progress | blocked | ready | done

## Workflow A
Transcript → LLM → Schema Validation → Decision Policy
→ Confirmed/Human Review/Not Task
→ Dependency → PostgreSQL → Calendar/Email

## Workflow B
Schedule Trigger → Read Active Tasks → Check Dependency
→ blocked/ready logic → Check Deadline → Reminder/Status Alert

Task blocked không nhận reminder kiểu "hãy hoàn thành task";
thay vào đó gửi blocked/status alert.

## Email và Calendar
Giữ trong MVP:
- Assignment Notification
- Calendar nếu có deadline
- Reminder
- Blocked Status Alert
- Dependency-ready notification

## Evaluation
- Task detection: Precision / Recall / F1
- Owner extraction: Accuracy / F1
- Deadline extraction: Accuracy
- Content classification: Accuracy / F1
- Commitment classification: Accuracy / F1
- Dependency detection: Precision / Recall / F1
- Expected decision: Accuracy
- JSON parse success rate

## Quy tắc sửa code
1. Không đổi schema nếu không được yêu cầu rõ.
2. Không trộn Decision Policy vào prompt extraction.
3. Không thêm confidence vào ground truth.
4. Không tự đoán owner, deadline, priority.
5. owners luôn là array.
6. depends_on luôn là array.
7. temporal_warning là optional.
8. Giữ raw output và final output tách biệt.
9. Final predicted JSON phải tương thích với ground truth.
