# Schema contract

Nguồn: dump PostgreSQL 18.3 tại docs/ai_agent_meeting và src/schemas.py.
Contract mô tả schema hiện có; không yêu cầu migration.

## PostgreSQL (public)

| Bảng | Cột và kiểu dữ liệu quan trọng |
| --- | --- |
| meetings | meeting_id text NOT NULL (PK); title text; meeting_date date; transcript_url text; created_at timestamptz NOT NULL DEFAULT now() |
| tasks | task_id integer NOT NULL (PK, sequence default); meeting_id text; item_id text; task text NOT NULL; owner text; owner_email text; deadline date; priority text; commitment text; confidence numeric(3,2); status text NOT NULL DEFAULT 'pending_review'; created_at và updated_at timestamptz NOT NULL DEFAULT now(); last_reminded_at timestamptz |
| task_dependencies | task_id integer NOT NULL; depends_on_task_id integer NOT NULL |
| employees | person_id varchar(50) NOT NULL (PK); name varchar(250) NOT NULL; email varchar(250) NOT NULL UNIQUE; department varchar(100) |

- tasks UNIQUE (meeting_id, item_id); cả hai cột cho phép NULL.
- tasks.meeting_id REFERENCES meetings(meeting_id) ON DELETE SET NULL.
- task_dependencies PRIMARY KEY (task_id, depends_on_task_id).
- Hai cột dependency REFERENCES tasks(task_id) ON DELETE CASCADE; CHECK task_id <> depends_on_task_id.
- Không có foreign key giữa tasks.owner và employees.
- priority CHECK: low | medium | high (hoặc NULL).
- commitment CHECK: explicit | tentative | ambiguous | not_applicable (hoặc NULL).
- confidence CHECK: 0..1 (hoặc NULL); đây là cột DB cũ, không thêm vào extraction/ground truth.

## Status và cập nhật

Constraint tasks_status_check cho phép chính xác:
pending_review | confirmed | rejected | editing | blocked | ready | in_progress | done.
DB không cho phép completed hoặc not_started.

Lifecycle: ready = Chưa bắt đầu; in_progress = Đang thực hiện;
blocked = Bị chặn; done = Hoàn thành.
pending_review, confirmed, rejected, editing phục vụ review; không tự chuyển confirmed thành ready.
Web chỉ cho ready -> in_progress/done và in_progress -> done.
Khi web hoàn thành task, service tự chuyển các task con blocked -> ready nếu mọi
tiền đề đều done trong cùng transaction. User không được tự chọn chuyển blocked.
Workflow B giữ quét unblock nền; web không sửa quan hệ dependency.

Trigger trg_tasks_updated_at BEFORE UPDATE ON tasks FOR EACH ROW gọi
public.set_updated_at(), gán NEW.updated_at = now().
Web vẫn SET updated_at = NOW() rõ ràng khi cập nhật status, kèm kiểm tra status cũ.

## Owner và quan hệ

owner là text nullable, không phải JSON/JSONB. Dữ liệu dump dùng chuỗi JSON
array ID như ["PERSON2"]. Web parse array string thành danh sách, hỗ trợ text
đơn như một owner và NULL/chuỗi rỗng thành danh sách rỗng; không tách tùy ý theo dấu phẩy.
Không suy đoán người phụ trách. Đối chiếu chính xác từng ID với employees.person_id
chỉ để hiển thị tên; giữ ID cho filter và giữ nguyên dữ liệu DB.
Meeting có nhiều task; dependency nối task với task tiền đề bằng integer PK,
không nối theo item_id đơn lẻ. Employees là danh bạ, không phải quan hệ FK bắt buộc.

## Extraction và Decision Policy

src/schemas.py là hợp đồng JSON độc lập với bảng DB.
RawMeetingOutput: meeting_id, meeting_date nullable, meeting_date_evidence nullable,
items (mặc định []). RawItem:
item_id (ITEM + chữ số), source_excerpt list[str], content_type,
description, owners list[str], deadline nullable string, deadline_text nullable string,
deadline_status, priority nullable, commitment, depends_on list[str] (mặc định []),
temporal_warning nullable optional.
content_type: task_candidate | proposal | decision | information.
deadline_status: resolved | resolved_with_warning | date_resolved_time_ambiguous |
event_based | ambiguous | missing | conflict | not_applicable.
priority: high | medium | low | null.
commitment: explicit | tentative | ambiguous | not_applicable.
FinalItem thêm expected_decision (confirmed | human_review | not_task) và review_reason nullable.
Decision Policy thêm hai trường này; LLM không quyết định chúng.
Không thêm confidence; không suy đoán owner/deadline/priority; owners và depends_on luôn là array.
Giữ metadata meeting và tương thích ground truth/final predicted JSON.
Workflow A chịu trách nhiệm ánh xạ JSON sang DB, tạo meeting/task/dependency.
Dashboard không ghi ngược vào extraction hoặc ground truth.
