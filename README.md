> Cập nhật: web đã bỏ đăng nhập staging/APP_PASSWORD, mở trực tiếp Transcript.
> Qwen3-8B + LoRA V6 là mặc định và đứng trước Gemini API. Lựa chọn trong session
> được giữ khi refresh/đổi trang; không fallback. Các hướng dẫn login/logout
> staging cũ bên dưới không còn áp dụng. API key các dịch vụ giữ nguyên.

# Meeting Task Extractor

LLM & Agent Logic Dashboard — staging:
Upload TXT → Gemini extraction → schema/business validation → Decision Policy → kết quả → download JSON.

## Source và phạm vi

- Entrypoint: **`app.py`** ở root.
- `src/llm_client.py`: Gemini API, prompt builder; web settings riêng qua `src/request_context.py`.
- `src/pipeline.py`: pipeline + retry hiện có, không thay đổi nghiệp vụ.
- `src/schemas.py`, `src/schema_validator.py`, `src/decision_policy.py`: schema/validation/policy hiện có.
- `ui/staging.py`: secrets, đăng nhập, upload, download, bộ đếm session, che secrets trong lỗi.
- `ui/operations.py`, `services/`: Human Review vẫn là demo session; Theo dõi công việc & cảnh báo dùng PostgreSQL.
- `run.py`: single-file/batch; `evaluation/`: evaluation offline. Hai luồng này giữ nguyên.
- Ask Transcript **chưa có trong source** và chưa triển khai ở staging; không có menu hỏi đáp.
- Gửi kết quả sang Workflow A qua n8n. Danh sách công việc đọc/cập nhật PostgreSQL trực tiếp; email/Calendar do n8n xử lý.

## Chạy local

Python **3.14** đã được kiểm thử local; dependencies trực tiếp được pin trong `requirements.txt`, không dùng pip freeze.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Trên Windows dùng `.venv\Scripts\activate`.

Cấu hình local theo một trong hai cách:

1. Tạo `.streamlit/secrets.toml` (được gitignore), rồi nhập giá trị thật riêng trên máy:

```toml
GEMINI_API_KEY = "your_api_key_here"
APP_PASSWORD = "your_staging_password"
GEMINI_MODEL = "gemini-3.6-flash"
```

2. Copy `.env.example` sang `.env`, thay hai placeholder bằng key/mật khẩu riêng.

`st.secrets` ưu tiên hơn environment; `.env` chỉ hỗ trợ local. Không gửi key/mật khẩu qua chat,
không commit `.env` hoặc `secrets.toml`. Nếu thiếu key/mật khẩu hoặc còn placeholder mẫu, app khóa an toàn.
Đăng nhập trước khi xem nội dung, chọn file `examples/demo_transcript.txt` (hoàn toàn giả lập), kiểm tra
ID/ngày rồi bấm Run Extraction. App không tự gọi API khi đổi widget/navigation/download.

Đăng xuất xóa dữ liệu họp và trạng thái đăng nhập. Bộ đếm giới hạn vẫn giữ trong cùng session;
đóng browser/session mới có thể reset, nên đây không phải quota tài khoản toàn hệ thống.

## Bảo vệ staging

- Chỉ `.txt`, UTF-8/UTF-8-SIG, không rỗng, tối đa 1 MiB (1,048,576 bytes).
- 20 extraction/session, gồm lượt thất bại; khai báo trong `config.py`.
- Tối đa 120 lần gọi Gemini/session, tính từng lần thử ở SDK boundary, gồm retry.
- `MAX_ASK_REQUESTS_PER_SESSION=30` dự phòng; không có Ask endpoint trong bản này.
- Web dùng model cấu hình `gemini-3.6-flash`, timeout 90 giây/lần gọi; SDK retry tắt riêng trên web
  để số lần gọi được kiểm soát bởi retry hiện có của pipeline (tối đa 5 retry, delay 2/4/8/16/32 giây).
- Khóa theo session và trạng thái busy chặn request đồng thời. Lỗi chỉ hiện thông báo ngắn;
  Logs giữ chẩn đoán đã che credentials, không hiển thị stack trace.
- Usage metadata (nếu có) nằm trong expander tại Logs. Không giả lập token fields thiếu.
- Raw/final giữ trong session; web không ghi `outputs/`. Download JSON UTF-8 theo meeting_id.
  Raw không parse được JSON vẫn xem nguyên văn, không cung cấp nút tải JSON hợp lệ cho nội dung đó.
- Dữ liệu session không bền vững: restart/redeploy/đóng session có thể làm mất dữ liệu.

Human Review chỉ thay session copy. Danh sách công việc cập nhật status trong PostgreSQL. Chưa có Ask Transcript để bật.

## Git local và GitHub private

`.gitignore` loại `.env*` (trừ example), mọi `secrets.toml`, `data/`, `outputs/`, venv/cache,
workspace local và các dạng file credential thường gặp. Dataset thật/GT không thuộc bản staging.
Chỉ `examples/demo_transcript.txt` được chia sẻ làm mẫu giả lập.

Trước mỗi commit:

```bash
git status --short
python tools/check_staged_secrets.py
python tools/check_staged_secrets.py --history
```

Scanner không in giá trị secrets; kết quả không thay thế việc xem xét staged files.
Nếu một key từng bị commit hoặc chia sẻ ngoài ý muốn: thu hồi key cũ và tạo key mới trước deploy.

Repository được chỉ định: **`dieunguyenistqb-coder/ai_agent_meeting`**. Yêu cầu triển khai: **private**, trừ khi chủ dự án cho phép public rõ ràng. Nếu chưa có `gh`/GitHub auth:

1. Trên GitHub tạo repository private, không thêm README, .gitignore hoặc license.
2. Tại root project, kiểm tra `git remote -v` và `git status`, rồi:

```bash
git remote add origin <GITHUB_REPOSITORY_URL>
git push -u origin main
```

Không đổi repository sang public. Không push cho đến khi scanner/staged review đạt.

## Deploy Streamlit Community Cloud

Chỉ thực hiện sau khi push thành công:

1. Đăng nhập Community Cloud, kết nối GitHub và cấp quyền repository **private**.
2. Create app → repository `dieunguyenistqb-coder/ai_agent_meeting` → branch **main** → main file **app.py**.
3. Advanced settings → chọn **Python 3.14** (khớp môi trường đã test local).
4. Trong Secrets nhập 3 trường TOML ở trên bằng giá trị thật: `GEMINI_API_KEY`, `APP_PASSWORD`,
   `GEMINI_MODEL = "gemini-3.6-flash"`. Không upload/commit file secrets thật.
5. Deploy, kiểm tra trang đăng nhập xuất hiện trước upload. Chỉ chia sẻ URL staging và mật khẩu
   qua kênh riêng cho nhóm test; giữ quyền truy cập Cloud hạn chế theo nhóm.
6. Manage app → logs để xem build/runtime logs; App settings → Secrets để sửa key/mật khẩu.
   Reboot app sau thay secrets nếu cần. Không dán logs chứa dữ liệu họp lên public issue.

Nguồn hướng dẫn chính thức:
[Deploy & Python settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy),
[Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management),
[Private repository access](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/connect-your-github-account).

Chưa có URL staging cho đến khi người sở hữu đăng nhập/push/deploy hoàn tất. CLI GitHub không bắt buộc
nếu dùng trình duyệt tạo repo và Git thông thường để push.

## Test

```bash
python -m compileall -q app.py config.py src ui services evaluation tests tools
python -m unittest discover -s tests -v
```

Tests mock Gemini; không gửi transcript thật hoặc tiêu tốn quota. Có test login/logout,
secrets thiếu/ưu tiên, upload, giới hạn/busy, metadata usage, raw/final download,
validation/policy, CLI/batch, evaluation và các màn hình demo khi bật flags.
Smoke test server chỉ kiểm tra startup/health; xác thực rendering/interaction bằng Streamlit AppTest.
Chưa kiểm tra request Gemini thật trong đợt staging này.

## CLI và evaluation giữ nguyên

```bash
python run.py data/transcripts/M001.txt --meeting-id M001 --meeting-date 2026-09-01
python run.py data/transcripts --batch
python run.py data/transcripts --batch --retry-failed
python -m evaluation.evaluator --pred-dir outputs/batch --gt-dir data/ground_truth --output-dir outputs/evaluation
```

Những đường dẫn `data/`, `outputs/` ở trên là dữ liệu riêng trên máy local, không đưa lên GitHub.
CLI vẫn dùng environment/.env, không yêu cầu APP_PASSWORD; web luôn yêu cầu đăng nhập.
Xem `evaluation/README.md` cho định nghĩa metrics và giới hạn match theo item_id.

## Luồng minh họa staging

Năm menu: Transcript → Kết quả trích xuất → Kiểm tra JSON → Xác nhận thủ công → Theo dõi công việc & cảnh báo.
Human Review vẫn mô phỏng trong session. Theo dõi công việc & cảnh báo dùng DB thật, kể cả khi đã tải demo.
`Tải dữ liệu demo` chỉ xuất hiện khi chưa có upload/kết quả; dữ liệu viết tay hoàn toàn giả lập.
Demo không chạy API/validation và được gắn nhãn riêng. Upload mới thay thế demo;
review/edit không sửa raw/final snapshot. `Đặt lại phiên demo` yêu cầu checkbox xác nhận,
xóa dữ liệu nhưng giữ đăng nhập và ngân sách API. Đăng xuất vẫn xóa dữ liệu phiên.
Status `completed` chỉ dành cho task session UI; vẫn hỗ trợ `done`/`ready` đã có,
không sửa enum/schema của pipeline. Cảnh báo dùng ngày local server hiện tại như trước,
không suy đoán deadline; blocked chỉ cảnh báo trạng thái, không nhắc hoàn thành.
Sau push main, kiểm tra Manage app trên ứng dụng Cloud hiện có để xác nhận redeploy;
không tạo app mới. Chỉ xác nhận deployment khi health/app của URL thực tế đã được kiểm tra.

## PostgreSQL task dashboard

Schema contract: [docs/schema_contract.md](docs/schema_contract.md), dựa trên
dump docs/ai_agent_meeting. Không cần migration.
Cài dependencies rồi thêm vào environment hoặc .env (không commit credential):
DB_HOST, DB_PORT (mặc định 5432), DB_NAME, DB_USER, DB_PASSWORD.
DB_SSLMODE tùy chọn, mặc định prefer; dùng require/verify-full theo cấu hình server.
Service này đọc environment trước .env; không đọc DB settings từ st.secrets.
Tài khoản cần SELECT trên public.tasks, public.meetings, public.employees, public.task_dependencies và
UPDATE(status, updated_at) trên public.tasks.

Chạy local:
```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Danh sách công việc hiển thị mọi task ở mọi meeting, gồm cả status review.
Owner là text chứa JSON array hoặc text đơn; filter dùng ID, tên được tra cứu
chính xác từ employees. Không tự đổi status review sang lifecycle.
Web chỉ cập nhật ready -> in_progress/done, in_progress -> done.
UPDATE kiểm tra status cũ để tránh ghi đè thay đổi đồng thời; updated_at = NOW().
Không sửa dependency; khi hoàn thành task, service tự mở khóa child đủ điều kiện. Không fallback sang demo khi lỗi DB.
Mỗi lần rerun đọc mới qua một connection ngắn, đóng sau khi đọc; không cache
dữ liệu/connection vào session. Bấm Làm mới danh sách để nhận thay đổi từ n8n.
Counter tính trên toàn bộ task, độc lập filter.
Theo dõi & cảnh báo chỉ đọc DB; monitoring tự động và thông báo do Workflow B thực hiện.

### Kiểm tra end-to-end với DB/n8n đã cấu hình

1. Gửi kết quả qua Workflow A; kiểm tra task mới được ghi vào DB.
2. Mở Danh sách công việc và bấm Làm mới; task xuất hiện đúng meeting/item/owners.
3. Mở task ready, đổi sang in_progress; kiểm tra status và updated_at trong DB.
4. Đổi in_progress sang done; kiểm tra DB và counter sau reload.
5. Với task con blocked, xác nhận web không có nút mở khóa.
6. Chạy Workflow B sau khi task tiền đề done; xác nhận task con thành ready.
7. Làm mới dashboard để thấy trạng thái mới.
8. Thử đổi trạng thái cùng lúc từ phiên khác: thao tác stale phải báo làm mới.
9. Ngắt kết nối DB: dashboard báo lỗi, không hiển thị dữ liệu demo thay thế.

Unit/UI tests dùng mock, không thay thế E2E với PostgreSQL và Workflow B thật.


Dependency trên dashboard được đọc bằng một batch query join task_dependencies
với tasks theo depends_on_task_id, không query theo từng task. Ba SELECT mỗi lần
refresh đọc tasks/meetings, dependency và employees.
Bảng vẫn có sáu cột; status blocked có dòng phụ nhỏ chỉ task tiền đề chưa done
đầu tiên và +N nếu còn nhiều task chưa done. Nếu tất cả đã done nhưng status
vẫn blocked, dòng phụ giữ các liên kết tiền đề trong lúc chờ hệ thống cập nhật.
Chi tiết hiển thị tất cả tiền đề, owner, deadline và cảnh báo quá hạn chưa done.
Ngày dùng ISO như UI hiện tại; NULL hiển thị Chưa xác định.
Bảng HTML cố định độ rộng hỗ trợ dòng phụ nhỏ; lọc/search vẫn ở phía trên,
không còn thao tác sort/download trực tiếp của st.dataframe.
Kiểm tra nhanh: lọc Meeting M066, mở ITEM002 để xem tiền đề ITEM001 (nếu
quan hệ trong DB vẫn giống dump). Bấm Làm mới để nhận status mới; UI không cho tự chọn unblock; service kiểm tra child khi hoàn thành parent.


## Theo dõi công việc & cảnh báo (trang gộp)

Chỉ còn menu Task Dashboard với nhãn Theo dõi công việc & cảnh báo;
menu Monitoring & Alerts cũ được bỏ, session đang ở route cũ chuyển sang trang gộp.
ENABLE_TASK_DASHBOARD điều khiển trang này; ENABLE_MONITORING cũ không tạo trang riêng.
UI monitoring/task demo cũ và ui/database_monitoring.py được bỏ; helper phân loại
attention_tasks và dependency vẫn dùng chung.

Snapshot đọc tasks (thêm last_reminded_at), meetings, batch dependency JOIN tasks,
employees và CURRENT_DATE/CURRENT_TIMESTAMP: 4 query mỗi refresh, không N+1.
Không dùng demo_store. Không đổi schema.
- Quá hạn: ready/in_progress/blocked và deadline < CURRENT_DATE.
- Sắp đến hạn: cùng lifecycle status, CURRENT_DATE <= deadline <= CURRENT_DATE + 3.
- Bị chặn: blocked.
- Cần Human Review: pending_review hoặc editing. confirmed/rejected không phải chờ review.
  Dump không có review_reason nên không suy đoán.
- done không có cảnh báo hạn; task không có cảnh báo vẫn hiển thị với dấu —.
- Một task có nhiều nhóm; counter tính trước filter.
- Bảng sáu cột: mã, mô tả, owner, hạn, trạng thái, cảnh báo; Meeting chỉ còn filter.
- Chi tiết giữ blocker/overdue, last_reminded_at hoặc Chưa gửi nhắc nhở.
- Chỉ update ready -> in_progress/done, in_progress -> done, kiểm tra status cũ
  trong UPDATE; rerun đọc DB và tính lại counter. Không confirm review hoặc cho user tự chọn unblock.

### Kiểm tra cảnh báo ngay

Thêm N8N_WORKFLOW_B_RUN_URL vào environment hoặc .env bằng URL webhook thực tế.
Không có URL thì nút bị vô hiệu hóa. Chỉ bấm nút mới gửi một POST JSON {}
(timeout 30 giây, không retry/redirect); sau phản hồi app đọc DB mới.
Webhook cần trả response sau khi toàn bộ workflow hoàn tất. HTTP 2xx chỉ xác nhận
phản hồi thành công, không chứng minh mọi bước nội bộ đã thành công nếu webhook
trả ngay khi bắt đầu. Timeout có thể nghĩa là workflow vẫn chạy: làm mới trước khi bấm lại.
Workflow có thể gửi thông báo theo cấu hình hiện có; app không thêm manual reminder.

### Test end-to-end trang gộp

1. Mở trang mới; xác nhận chỉ một menu quản lý task, năm counter, không có cột Meeting.
2. Task bình thường/done vẫn trong bảng; loại cảnh báo là — nếu không thuộc nhóm khác.
3. Lọc cảnh báo quá hạn/sắp đến hạn/review; đối chiếu ngày DB và lifecycle/review status.
4. Mở M066 · ITEM002 (nếu DB còn giữ dump), xem tiền đề ITEM001 và cảnh báo quá hạn.
5. Đổi task ready -> in_progress -> done; đối chiếu DB, bảng và counter sau mỗi lần.
6. Cấu hình URL thật, bấm Kiểm tra cảnh báo ngay; kiểm tra execution của workflow,
   response và dữ liệu sau refresh (gồm blocked -> ready khi tiền đề done).
7. Kiểm tra lỗi/timeout và không có POST khi chỉ đổi filter hoặc làm mới.
Tests tự động mock webhook để không gửi email; kiểm tra thật chỉ thực hiện khi chủ
hệ thống chủ động bấm nút. Không thêm Workflow C.


### Mở khóa đồng bộ sau khi hoàn thành task

DatabaseTaskService.update_status dùng một transaction READ COMMITTED:
update parent có kiểm tra status cũ, khóa các child blocked theo task_id,
rồi UPDATE child blocked -> ready khi NOT EXISTS tiền đề nào chưa done.
Query khóa và query kiểm tra tách riêng để sau khi chờ một transaction khác,
việc kiểm tra thấy trạng thái parent mới commit. Nếu bước nào lỗi, rollback
toàn bộ, gồm cập nhật parent. Không có email/webhook trong thao tác này.
Task con ready/in_progress/done không bị đổi; cập nhật khác done không kiểm tra child.
UI rerun sau commit cập nhật bảng và counter. Không sửa Workflow B.

Workflow B vẫn quét nền. Lưu ý: nếu workflow chỉ gửi thông báo cho các dòng
vừa được chính nó đổi blocked -> ready, nó sẽ không tự gửi thông báo cho dòng
đã được web mở khóa; cần kiểm tra flow thông báo hiện có trước khi kỳ vọng email.
Thay đổi này không thêm cờ/outbox hoặc cơ chế gửi thông báo mới.

Test PostgreSQL trên bảng TEMP (không sửa tasks thật):
RUN_DB_TESTS=1 .venv/bin/python -m unittest discover -s tests -p test_dependency_transaction.py -v

Với M066: nếu ITEM001 còn ready/in_progress và ITEM002 blocked, đánh dấu
ITEM001 done rồi kiểm tra ITEM002 thành ready ngay. Nếu ITEM001 đã done từ
trước bản sửa, thao tác cũ không tự chạy lại: dùng kiểm tra nền để đối soát hoặc
tạo một bộ task thử mới qua flow hiện có; không đổi ngược task thật để test.


### Nút kiểm tra cảnh báo: phản hồi sớm

N8N_WORKFLOW_B_RUN_URL trong environment hoặc .env bật nút; .env.example có
URL local http://localhost:5678/webhook/workflow-b-run-now.
Service services/n8n_service.py::run_workflow_b gửi JSON {} (không credential DB).
Nút khóa trong lúc xử lý; spinner hiển thị trạng thái. Sau HTTP 2xx,
đọc snapshot DB 3 lần, mỗi lần chờ 0,75 giây, dùng kết quả lần cuối.
Không có vòng lặp vô hạn hoặc retry POST. HTTP success không chứng minh execution
đã kết thúc; workflow lâu hơn cửa sổ này cần bấm Làm mới danh sách sau đó.
Nút Làm mới chỉ đọc DB, không gọi webhook.
Kiểm thử E2E: bật n8n, publish Workflow B, bấm nút và kiểm tra execution mới;
đối chiếu child blocked đủ điều kiện thành ready và deadline branch.
Khi n8n tắt phải thấy lỗi thân thiện; thiếu URL nút bị vô hiệu hóa.
Không chỉnh workflow, logic dependency/update status hiện có hoặc gửi email từ web.

### Workflow C — Gửi nhắc nhở thủ công

N8N_WORKFLOW_C_REMINDER_URL được đọc từ environment, rồi .env; mặc định
http://localhost:5678/webhook/task-reminder.
services/n8n_service.py::run_workflow_c_reminder(task_id) gửi POST JSON
{"task_id": <integer>} với timeout 30s, không retry/redirect, không credential DB.
Response cần JSON object có status:
sent | too_soon | done | no_email | not_found | invalid_task_id | error.
UI xử lý từng status, timeout/lỗi kết nối/phản hồi không hợp lệ bằng thông báo
an toàn; HTTP lỗi không được coi là sent. Không gửi SMTP từ Streamlit.

Trong chi tiết task, bấm Gửi nhắc nhở. Nút khóa theo session khi đang chờ;
rerun sau response đọc DB mới, bao gồm last_reminded_at. Refresh thông thường
không gửi lại POST. Chống gửi lặp giữa nhiều session và thời gian chờ do Workflow C
quản lý (too_soon); timeout không tự retry vì nhắc nhở có thể đã được gửi.

Test E2E: publish Workflow C, cấu hình URL, mở task có email rồi bấm nút;
kiểm tra execution/payload và last_reminded_at sau sent. Thử nhắc lại sớm,
task done, thiếu email, task bị xóa và n8n mất kết nối để kiểm tra thông báo.
Tests tự động mock POST, không gửi email thật. Không đổi workflow A/B hoặc schema.

## Chọn model extraction trên web

Trước Run Extraction, chọn Gemini API hoặc Qwen3-8B + LoRA V6.
Gemini tái sử dụng SDK, prompt_v1 và retry/quota hiện có. Qwen dùng
QWEN_API_URL và QWEN_API_KEY trong environment/.env; key rỗng thì không gửi header.
POST gồm meeting_date và transcript; X-API-Key tùy chọn, timeout 180s,
không retry/redirect/fallback sang Gemini.
API cần trả {ok:true, model_version:"v6", prompt_version:"prompt_v6", items:[...]}.
items phải theo raw schema, không chứa expected_decision/review_reason do LLM quyết định.
Service giữ meeting_id/date/evidence từ đầu vào; validation và Decision Policy chạy như cũ.
Metadata provider/model/prompt chỉ dùng hiển thị, không thêm vào final JSON/n8n.
Đổi radio không tự chạy API và không đổi nhãn model của kết quả đã chạy.
CLI/batch vẫn dùng đường extraction cũ. Cấu hình đăng nhập staging hiện có giữ nguyên.

Test: cấu hình Qwen endpoint, chọn Qwen và Run Extraction; xác nhận nhãn prompt_v6,
review trên web rồi gửi final reviewed JSON như trước. Tắt Colab: phải báo lỗi Qwen,
không có lượt gọi Gemini thay thế. Chọn Gemini và chạy lại để dùng Gemini rõ ràng.

## Xác nhận toàn bộ batch trước khi gửi

Kết quả trích xuất có item pending hiển thị Tiếp tục xác nhận, chuyển sang
Xác nhận thủ công. Mỗi item được xác nhận, sửa rồi xác nhận hoặc bỏ.
Không tự submit sau review; cả hai trang dùng nút Xác nhận & gửi vào hệ thống.
Nút bị khóa khi còn pending hoặc payload không hợp lệ.

Trước mỗi POST, build_submission dựng lại từ extraction gốc và lịch sử review,
loại item bị bỏ, validate FinalMeetingOutput và business rules, kiểm tra ID trùng
và dependency còn tồn tại. Không chạy lại Decision Policy; không ép commitment,
content_type hoặc trường semantic khác để đạt confirmed. Session lưu review_status
confirmed_by_human/rejected; payload giữ schema hiện có, không thêm field này.
Validation sai (kể cả owner không có evidence hoặc deadline/status mâu thuẫn sau sửa)
chặn POST và hiển thị lý do. Không tự xóa dependency để che lỗi.
Không thêm batch table/idempotency; nhấn gửi lần nữa vẫn có thể gửi lại batch.
