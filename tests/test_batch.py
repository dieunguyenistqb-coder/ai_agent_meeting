import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run
from src import pipeline
from src.decision_policy import apply_decision_policy


def response(payload):
    return json.dumps({key: payload[key] for key in
                       ("meeting_id", "meeting_date", "meeting_date_evidence")} | {
        "items": [dict(item_id="ITEM001", source_excerpt=["Nam: Tôi sẽ làm API."],
                       content_type="task_candidate", description="Làm API", owners=["Nam"],
                       deadline_status="missing", commitment="explicit", depends_on=[])]})


class BatchTests(unittest.TestCase):
    def test_daily_quota_markers_do_not_retry(self):
        from google.genai.errors import ClientError
        for marker in ("RESOURCE_EXHAUSTED", "generate_content_free_tier_requests",
                       "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                       "quota exceeded", "exceeded your current quota"):
            error = ClientError(429, {"error": {"message": marker}})
            with self.subTest(marker=marker), patch.object(pipeline, "call_llm", side_effect=error) as llm, patch.object(
                    pipeline.time, "sleep") as sleep:
                with self.assertRaises(pipeline.DailyQuotaExceededError) as raised:
                    pipeline.call_llm_with_retry({"meeting_id": "M001"})
                self.assertIs(raised.exception.__cause__, error)
                self.assertIn(str(error), str(raised.exception))
                llm.assert_called_once()
                sleep.assert_not_called()

    def test_daily_quota_report_and_continue(self):
        from google.genai.errors import ClientError
        self.transcript("M001")
        self.transcript("M002")

        def extract(payload):
            if payload["meeting_id"] == "M001":
                raise ClientError(429, {"error": {"message": "quota exceeded"}})
            return response(payload)

        with patch.object(pipeline, "call_llm", side_effect=extract) as llm, patch.object(pipeline.time, "sleep") as sleep:
            rows = self.batch()
        self.assertEqual(llm.call_count, 2)
        sleep.assert_not_called()
        self.assertIn("DailyQuotaExceededError", rows[0]["error_message"])
        self.assertFalse(rows[0]["decision_policy_ran"])
        self.assertTrue(rows[1]["decision_policy_ran"])
        with (self.outputs / "validation_report.csv").open(newline="") as file:
            self.assertEqual(list(csv.DictReader(file))[0]["error_message"], rows[0]["error_message"])

    def test_retry_backoff_and_recovery(self):
        from google.genai.errors import ClientError, ServerError
        for error in (ClientError(429, {"error": {"message": "rate limited"}}),
                      ServerError(503, {"error": {"message": "high demand"}})):
            with self.subTest(code=error.code), patch.object(
                    pipeline, "call_llm", side_effect=[error] * 5 + ["ok"]) as llm, patch.object(
                    pipeline.time, "sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.call_llm_with_retry({"meeting_id": "M001"}), "ok")
                self.assertEqual(llm.call_count, 6)
                self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4, 8, 16, 32])

    def test_exhausted_retry_continues_batch(self):
        from google.genai.errors import ServerError
        self.transcript("M001")
        self.transcript("M002")

        def extract(payload):
            if payload["meeting_id"] == "M001":
                raise ServerError(503, {"error": {"message": "high demand"}})
            return response(payload)

        with patch.object(pipeline, "call_llm", side_effect=extract) as llm, patch.object(pipeline.time, "sleep") as sleep:
            rows = self.batch()
        self.assertEqual(llm.call_count, 7)
        self.assertEqual(sleep.call_count, 5)
        self.assertIn("503", rows[0]["error_message"])
        self.assertIn("5 lần retry (6 lần gọi)", rows[0]["error_message"])
        self.assertIn("high demand", rows[0]["error_message"])
        self.assertFalse(rows[0]["decision_policy_ran"])
        self.assertTrue(rows[1]["decision_policy_ran"])
        with (self.outputs / "validation_report.csv").open(newline="") as file:
            self.assertEqual(list(csv.DictReader(file))[0]["error_message"], rows[0]["error_message"])

    def test_non_retryable_error_is_not_retried(self):
        from google.genai.errors import ClientError
        self.transcript("M001")
        with patch.object(pipeline, "call_llm", side_effect=ClientError(400, {})) as llm, patch.object(pipeline.time, "sleep") as sleep:
            self.assertTrue(self.batch()[0]["error_message"])
        self.assertEqual(llm.call_count, 1)
        sleep.assert_not_called()

    def test_retry_failed_preserves_success_and_ignores_new_files(self):
        self.transcript("M001")
        self.transcript("M002")
        with patch.object(pipeline, "call_llm", side_effect=lambda p: response(p) if p["meeting_id"] == "M001" else "bad JSON"):
            self.batch()
        final_path = self.outputs / "M001/predicted_final.json"
        original = final_path.read_bytes()
        original_mtime = final_path.stat().st_mtime_ns
        self.transcript("M003")
        with patch.object(pipeline, "call_llm", side_effect=response) as llm:
            rows = self.batch(retry_failed=True)
        self.assertEqual(llm.call_count, 1)
        self.assertEqual(llm.call_args.args[0]["meeting_id"], "M002")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not row["error_message"] for row in rows))
        self.assertEqual(final_path.read_bytes(), original)
        self.assertEqual(final_path.stat().st_mtime_ns, original_mtime)
        report = (self.outputs / "validation_report.csv").read_bytes()
        with patch.object(pipeline, "call_llm") as llm:
            self.batch(retry_failed=True)
        llm.assert_not_called()
        self.assertEqual((self.outputs / "validation_report.csv").read_bytes(), report)

    def test_retry_failed_requires_valid_report_and_matching_transcripts(self):
        self.transcript("M001")
        with self.assertRaises(FileNotFoundError):
            self.batch(retry_failed=True)
        with patch.object(pipeline, "call_llm", return_value="bad JSON"):
            self.batch()
        report_path = self.outputs / "validation_report.csv"
        original = report_path.read_bytes()
        (self.inputs / "M001.txt").rename(self.inputs / "M002.txt")
        with self.assertRaisesRegex(ValueError, "Thiếu transcript"):
            self.batch(retry_failed=True)
        self.assertEqual(report_path.read_bytes(), original)
        report_path.write_text("wrong,columns\n")
        with self.assertRaisesRegex(ValueError, "Report"):
            self.batch(retry_failed=True)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.outputs = self.root / "outputs"

    def transcript(self, name, text="Nam: Tôi sẽ làm API."):
        (self.inputs / f"{name}.txt").write_text(text, encoding="utf-8")

    def batch(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return run.run_batch(self.inputs, self.outputs, **kwargs)

    def test_success_metadata_and_output(self):
        self.transcript("M001", "\ufeffNgày họp: 13-09-2026\nNam: Tôi sẽ làm API.")
        self.transcript("M002", "meeting_date: 2026-10-24\nNam: Tôi sẽ làm API.")
        self.transcript("M003")
        (self.inputs / "ignore.json").write_text("{}")
        evidence = {"evidence": "provided", "reasoning": "provided"}
        with patch.object(pipeline, "call_llm", side_effect=response) as llm:
            rows = self.batch(meeting_date="2026-09-01", meeting_date_evidence=evidence)
        self.assertEqual(llm.call_count, 3)
        for name, day, expected_evidence in [("M001", "2026-09-13", None),
                                              ("M002", "2026-10-24", None),
                                              ("M003", "2026-09-01", evidence)]:
            raw = json.loads((self.outputs / name / "predicted_raw.json").read_text())
            final = json.loads((self.outputs / name / "predicted_final.json").read_text())
            self.assertEqual(final["meeting_id"], name)
            self.assertEqual(final["meeting_date"], day)
            self.assertEqual(final["meeting_date_evidence"], expected_evidence)
            self.assertNotIn("expected_decision", raw["items"][0])
            self.assertEqual(final["items"][0]["expected_decision"], "confirmed")
        self.assertTrue(all(all(row[field] for field in run.REPORT_FIELDS[1:5]) for row in rows))
        with (self.outputs / "validation_report.csv").open(newline="") as file:
            reader = csv.DictReader(file)
            self.assertEqual(reader.fieldnames, run.REPORT_FIELDS)
            self.assertEqual(len(list(reader)), 3)

    def test_failures_preserve_raw_skip_policy_and_continue(self):
        for name in ("parse", "schema", "business", "success", "api"):
            self.transcript(name)
        captured = {}

        def extract(payload):
            name = payload["meeting_id"]
            if name == "api":
                raise RuntimeError("API unavailable")
            data = json.loads(response(payload))
            if name == "schema":
                data["items"][0]["owners"] = "Nam"
            if name == "business":
                data["items"][0]["depends_on"] = ["ITEM999"]
            captured[name] = "not JSON" if name == "parse" else json.dumps(data)
            return captured[name]

        with patch.object(pipeline, "call_llm", side_effect=extract), patch.object(
                pipeline, "apply_decision_policy", wraps=apply_decision_policy) as policy:
            rows = {row["meeting_id"]: row for row in self.batch()}
        self.assertEqual(policy.call_count, 1)
        for name, flags in {"parse": [False, False, False, False],
                            "schema": [True, False, False, False],
                            "business": [True, True, False, False],
                            "api": [False, False, False, False],
                            "success": [True, True, True, True]}.items():
            self.assertEqual([rows[name][field] for field in run.REPORT_FIELDS[1:5]], flags)
            self.assertEqual((self.outputs / name / "predicted_final.json").exists(), name == "success")
            if name != "api":
                self.assertEqual((self.outputs / name / "predicted_raw.json").read_text(), captured[name])
            if name != "success":
                self.assertTrue(rows[name]["error_message"])
        with (self.outputs / "validation_report.csv").open(newline="") as file:
            report = {row["meeting_id"]: row for row in csv.DictReader(file)}
        self.assertEqual(report["business"]["error_message"], rows["business"]["error_message"])

    def test_failed_rerun_removes_stale_final(self):
        self.transcript("M001")
        with patch.object(pipeline, "call_llm", side_effect=response):
            self.batch()
        with patch.object(pipeline, "call_llm", return_value="invalid"):
            self.batch()
        self.assertFalse((self.outputs / "M001/predicted_final.json").exists())
        self.assertEqual((self.outputs / "M001/predicted_raw.json").read_text(), "invalid")

    def test_missing_null_invalid_dates_and_empty_input(self):
        self.transcript("unknown")
        self.transcript("null", "meeting_date: null\nNam: Tôi sẽ làm API.")
        self.transcript("bad_date", "Ngày họp: 31-02-2026\nNam: Tôi sẽ làm API.")
        self.transcript("empty", " \n")
        with patch.object(pipeline, "call_llm", side_effect=response) as llm:
            rows = {row["meeting_id"]: row for row in self.batch()}
        self.assertEqual(llm.call_count, 2)
        self.assertTrue(all(call.args[0]["meeting_date"] is None for call in llm.call_args_list))
        for name in ("bad_date", "empty"):
            self.assertTrue(rows[name]["error_message"])
            self.assertFalse((self.outputs / name / "predicted_final.json").exists())

    def test_invalid_or_empty_folder(self):
        with self.assertRaisesRegex(ValueError, "Không tìm thấy"):
            self.batch()
        with self.assertRaisesRegex(ValueError, "Không phải folder"):
            run.run_batch(self.root / "missing", self.outputs)


if __name__ == "__main__":
    unittest.main()
