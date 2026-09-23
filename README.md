# Meeting Task Extractor

LLM & Agent Logic Dashboard — staging:
Upload TXT → Gemini extraction → schema/business validation → Decision Policy → kết quả → download JSON.

## Source và phạm vi

- Entrypoint: **`app.py`** ở root.
- `src/llm_client.py`: Gemini API, prompt builder; web settings riêng qua `src/request_context.py`.
- `src/pipeline.py`: pipeline + retry hiện có, không thay đổi nghiệp vụ.
- `src/schemas.py`, `src/schema_validator.py`, `src/decision_policy.py`: schema/validation/policy hiện có.
- `ui/staging.py`: secrets, đăng nhập, upload, download, bộ đếm session, che secrets trong lỗi.
- `ui/operations.py`, `services/`: các màn hình quản lý demo có sẵn; **bật mặc định** trong `config.py`, chỉ thay đổi session.
- `run.py`: single-file/batch; `evaluation/`: evaluation offline. Hai luồng này giữ nguyên.
- Ask Transcript **chưa có trong source** và chưa triển khai ở staging; không có menu hỏi đáp.
- Không kết nối n8n, PostgreSQL, email hoặc Calendar.

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

Bật các flag quản lý nếu muốn demo nội bộ; các thao tác review/task chỉ thay session copy,
không sửa extraction gốc hoặc lưu PostgreSQL. Chưa có Ask Transcript để bật.

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

Sáu menu: Transcript → Kết quả trích xuất → Kiểm tra JSON → Xác nhận thủ công → Danh sách công việc → Theo dõi & cảnh báo.
Ba trang cuối chỉ mô phỏng trong session, không có database, n8n hay notification nền.
`Tải dữ liệu demo` chỉ xuất hiện khi chưa có upload/kết quả; dữ liệu viết tay hoàn toàn giả lập.
Demo không chạy API/validation và được gắn nhãn riêng. Upload mới thay thế demo;
review/edit không sửa raw/final snapshot. `Đặt lại phiên demo` yêu cầu checkbox xác nhận,
xóa dữ liệu nhưng giữ đăng nhập và ngân sách API. Đăng xuất vẫn xóa dữ liệu phiên.
Status `completed` chỉ dành cho task session UI; vẫn hỗ trợ `done`/`ready` đã có,
không sửa enum/schema của pipeline. Cảnh báo dùng ngày local server hiện tại như trước,
không suy đoán deadline; blocked chỉ cảnh báo trạng thái, không nhắc hoàn thành.
Sau push main, kiểm tra Manage app trên ứng dụng Cloud hiện có để xác nhận redeploy;
không tạo app mới. Chỉ xác nhận deployment khi health/app của URL thực tế đã được kiểm tra.
