import argparse
import csv
import json
import re
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from pydantic import ValidationError

from src.pipeline import PipelineError, process_transcript
from src.schema_validator import OutputValidationError

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "outputs" / "raw"
FINAL_DIR = ROOT / "outputs" / "final"
REPORT_FIELDS = ["meeting_id", "parse_success", "schema_valid", "business_valid",
                 "decision_policy_ran", "error_message"]


def read_batch_report(path):
    with path.open(encoding="utf-8", newline="") as report:
        reader = csv.DictReader(report)
        if reader.fieldnames != REPORT_FIELDS:
            raise ValueError(f"Report không đúng các cột yêu cầu: {path}")
        rows = {}
        for row in reader:
            meeting_id = row["meeting_id"]
            if not meeting_id or meeting_id in rows or row.get("error_message") is None or None in row:
                raise ValueError(f"Report có dòng thiếu hoặc trùng meeting_id: {path}")
            for field in REPORT_FIELDS[1:5]:
                if row[field] not in {"True", "False"}:
                    raise ValueError(f"Report có giá trị {field} không hợp lệ: {path}")
                row[field] = row[field] == "True"
            rows[meeting_id] = row
        return rows


def write_batch_report(path, rows):
    # Keep the previous snapshot intact if the process stops during writing.
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as report:
        writer = csv.DictWriter(report, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows.values())
    temporary.replace(path)


def transcript_metadata(transcript, meeting_date=None, meeting_date_evidence=None):
    """Only read an explicit date header; never infer a date from dialogue."""
    first_line = transcript.splitlines()[0].lstrip("\ufeff").strip()
    header = re.fullmatch(r"(?:Ngày họp|meeting_date)\s*:\s*(.*)", first_line,
                          flags=re.IGNORECASE)
    if header:
        value = header.group(1).strip()
        if re.fullmatch(r"\d{2}-\d{2}-\d{4}", value):
            value = datetime.strptime(value, "%d-%m-%Y").date().isoformat()
        return parse_meeting_date(value), None
    return meeting_date, meeting_date_evidence


def run_batch(input_path, output_dir=None, meeting_date=None, meeting_date_evidence=None,
              retry_failed=False):
    input_dir = Path(input_path)
    if not input_dir.is_dir():
        raise ValueError(f"Không phải folder transcript: {input_dir}")
    files = sorted(path for path in input_dir.glob("*.txt") if path.is_file())
    if not files:
        raise ValueError(f"Không tìm thấy transcript .txt trong {input_dir}")
    output_dir = Path(output_dir) if output_dir is not None else ROOT / "outputs" / "batch"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "validation_report.csv"
    rows = read_batch_report(report_path) if retry_failed else {}
    if retry_failed:
        failed_ids = {key for key, row in rows.items()
                      if row["error_message"] or not all(row[field] for field in REPORT_FIELDS[1:5])}
        available = {path.stem for path in files}
        missing = failed_ids - available
        if missing:
            raise ValueError(f"Thiếu transcript cho meeting_id đã fail: {', '.join(sorted(missing))}")
        files = [path for path in files if path.stem in failed_ids]
        if not files:
            print("Không có meeting_id lỗi cần chạy lại.")
            return list(rows.values())
    write_batch_report(report_path, rows)
    for input_file in files:
        row = dict.fromkeys(REPORT_FIELDS, False)
        row.update(meeting_id=input_file.stem, error_message="")
        try:
            meeting_dir = output_dir / input_file.stem
            meeting_dir.mkdir(parents=True, exist_ok=True)
            raw_path = meeting_dir / "predicted_raw.json"
            final_path = meeting_dir / "predicted_final.json"
            # A failed rerun must not expose artifacts from an earlier run.
            final_path.unlink(missing_ok=True)
            raw_path.unlink(missing_ok=True)
            transcript = input_file.read_text(encoding="utf-8-sig")
            if not transcript.strip():
                raise ValueError("Transcript không được để trống")
            day, evidence = transcript_metadata(transcript, meeting_date, meeting_date_evidence)
            try:
                raw_text, raw_obj, final_obj = process_transcript(
                    transcript, input_file.stem, day, evidence)
            except PipelineError as failure:
                if failure.raw_output is not None:
                    raw_path.write_text(failure.raw_output, encoding="utf-8")
                exc = failure.error
                if failure.validated_object is not None:
                    row.update(parse_success=True, schema_valid=True, business_valid=True)
                elif isinstance(exc, OutputValidationError):
                    row["parse_success"] = not isinstance(exc.__cause__, json.JSONDecodeError)
                    row["schema_valid"] = row["parse_success"] and not isinstance(exc.__cause__, ValidationError)
                raise exc
            row.update(parse_success=True, schema_valid=True, business_valid=True,
                       decision_policy_ran=True)
            raw_path.write_text(raw_text, encoding="utf-8")
            final_path.write_text(json.dumps(final_obj.model_dump(), ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except Exception as exc:
            row["error_message"] = f"{type(exc).__name__}: {exc}"
        rows[input_file.stem] = row
        write_batch_report(report_path, rows)
        print(f"[{input_file.stem}] {row['error_message'] or 'OK'}")
    return list(rows.values())

def parse_meeting_date(value: str):
    if value == "null":
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("meeting-date phải có dạng YYYY-MM-DD hoặc null")
    return value


def parse_meeting_date_evidence(value: str):
    try:
        evidence = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("meeting-date-evidence phải là JSON object hoặc null") from exc
    if evidence is not None and not isinstance(evidence, dict):
        raise argparse.ArgumentTypeError("meeting-date-evidence phải là JSON object hoặc null")
    return evidence


def main(input_path: str, meeting_id: str, meeting_date: str | None,
         meeting_date_evidence: dict | None = None):
    input_file = Path(input_path)
    transcript = input_file.read_text(encoding="utf-8")
    if not transcript.strip():
        raise ValueError("Transcript không được để trống")
    print(f"[1/4] Gọi LLM cho: {input_file.name}")
    raw_output_path = RAW_DIR / f"{input_file.stem}_raw.json"
    try:
        raw_text, raw_obj, final_obj = process_transcript(
            transcript, meeting_id, meeting_date, meeting_date_evidence)
    except PipelineError as failure:
        if failure.raw_output is not None:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            FINAL_DIR.mkdir(parents=True, exist_ok=True)
            raw_output_path.write_text(failure.raw_output, encoding="utf-8")
            print(f"[2/4] Đã lưu raw output: {raw_output_path}")
            print("[3/4] Validate schema + business rules...")
        raise failure.error

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    raw_output_path.write_text(raw_text, encoding="utf-8")
    print(f"[2/4] Đã lưu raw output: {raw_output_path}")
    print("[3/4] Validate schema + business rules...")
    print("      Schema và business rules hợp lệ.")

    final_output_path = FINAL_DIR / f"{input_file.stem}_final.json"
    final_output_path.write_text(
        json.dumps(final_obj.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[4/4] Đã áp Decision Policy: {final_output_path}")

    print("\nKẾT QUẢ:")
    print(json.dumps(final_obj.model_dump(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input",
        help="Đường dẫn file transcript .txt (UTF-8)",
    )
    parser.add_argument("--batch", action="store_true", help="Chạy các file .txt trong folder input")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Chỉ chạy lại meeting lỗi từ validation_report.csv trong output-dir")
    parser.add_argument("--output-dir", help="Folder output batch (mặc định outputs/batch)")
    parser.add_argument("--meeting-id", help="Mã cuộc họp, ví dụ M001")
    parser.add_argument("--meeting-date", type=parse_meeting_date, default=argparse.SUPPRESS,
                        help="Ngày cuộc họp YYYY-MM-DD, hoặc null nếu chưa xác định")
    parser.add_argument("--meeting-date-evidence", type=parse_meeting_date_evidence,
                        default=None, help="JSON object chứa bằng chứng ngày họp (mặc định null)")
    args = parser.parse_args()
    if args.batch:
        if args.meeting_id:
            parser.error("Batch lấy meeting_id từ tên file; không dùng --meeting-id")
        try:
            rows = run_batch(args.input, args.output_dir, getattr(args, "meeting_date", None),
                             args.meeting_date_evidence, retry_failed=args.retry_failed)
        except (ValueError, OSError) as exc:
            parser.exit(1, f"{exc}\n")
        parser.exit(1 if any(row["error_message"] for row in rows) else 0)
    if args.retry_failed:
        parser.error("--retry-failed chỉ dùng với --batch")
    if not args.meeting_id or not hasattr(args, "meeting_date"):
        parser.error("Chạy một file cần --meeting-id và --meeting-date")
    if args.output_dir:
        parser.error("--output-dir chỉ dùng với --batch")
    try:
        main(args.input, args.meeting_id, args.meeting_date, args.meeting_date_evidence)
    except OutputValidationError as exc:
        parser.exit(1, f"{exc}\nĐã dừng trước Decision Policy; không ghi final JSON mới.\n")
