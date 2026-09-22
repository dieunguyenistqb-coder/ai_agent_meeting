# Offline evaluation

```bash
python -m evaluation.evaluator --pred-dir outputs/batch --gt-dir data/ground_truth --output-dir outputs/evaluation
```

Đọc GT `*.json` và prediction `*/predicted_final.json`; không đọc raw hoặc file `.txt`,
không gọi LLM, không chạy lại Decision Policy. Có thể thay bộ GT mà không sửa code.
Match bằng `meeting_id` trong JSON, sau đó `item_id`, không dùng tên file hoặc thứ tự.
ID trùng, JSON lỗi, thiếu field chấm điểm hoặc sai kiểu dữ liệu sẽ dừng và báo đường dẫn,
không âm thầm bỏ qua dữ liệu. Cho phép metadata GT bổ sung; không áp business validation
lên prediction để tránh loại bỏ chính lỗi cần đánh giá.

## Quy ước

- Item detection: mọi item, gồm task_candidate/proposal/decision/information. ID khớp là TP,
  chỉ GT là FN, chỉ prediction là FP. Meeting thiếu prediction hoặc GT cũng được tính.
- Accuracy và Macro F1 của field chỉ tính trên các item ghép được. Luôn kèm support;
  không dùng điểm field để thay thế detection. Macro F1 dùng tập nhãn xuất hiện ở một trong
  hai phía trong các cặp ghép, không tính các enum chưa xuất hiện.
- Owners exact match so sánh tập, không phụ thuộc thứ tự. Owners/dependency P/R/F1 là micro
  trên toàn bộ item kể cả thiếu/thừa; quan hệ được phân biệt theo meeting và source item.
- Deadline so sánh chính xác, `null == null`; không resolve lại ngày.
- False Automatic Task Creation Rate = số predicted confirmed có GT khác confirmed
  (hoặc không có GT tương ứng) / tổng predicted confirmed.
- Mẫu số 0: `null` trong JSON, ô trống trong CSV; không tự gán điểm hoàn hảo cho tập rỗng.
- Tổng hợp bằng pooled counts, không lấy trung bình các meeting. Description/source_excerpt
  không chấm exact-match. Priority/temporal_warning chưa chấm trong phiên bản này.
- Missing/extra item có một dòng lỗi `field=item`, không tạo lỗi field giả trên item chưa ghép.
- Chỉ match ID có giới hạn: nếu LLM đổi số thứ tự item, nội dung tương đương vẫn có thể lệch
  cặp. Chưa có semantic matching ở giai đoạn này.

## Output

- `evaluation_summary.json`: metrics, count, class breakdown, quy ước, meeting thiếu và lỗi theo field/type.
- `evaluation_summary.csv`: dạng dài metric/value, tên metric phân cấp bằng dấu chấm.
- `per_meeting_results.csv`: trạng thái meeting, item count, error count và metrics từng meeting.
- `error_analysis.csv`: ID hai phía, field, giá trị hai phía (JSON encoded), loại lỗi.

Bộ thử hiện tại có 6 GT nhưng chỉ 5 final prediction JSON. `sample_01` có file
`predicted_final.txt` chứa transcript, không phải final JSON; được ghi thiếu prediction,
5 item GT tính FN. Không sửa hoặc tự tạo prediction để bù dữ liệu thiếu.
