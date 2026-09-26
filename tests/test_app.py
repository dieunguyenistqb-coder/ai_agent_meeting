"""Exercise dashboard reruns without calling a provider API."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests
from streamlit.testing.v1 import AppTest

from src import pipeline


APP = str(Path(__file__).resolve().parents[1] / "app.py")


TEST_PASSWORD = 'local-test-password-not-a-credential'


def make_app():
    at = AppTest.from_file(APP, default_timeout=15)
    at.secrets['APP_PASSWORD'] = TEST_PASSWORD
    at.secrets['GEMINI_API_KEY'] = 'mock-api-key-not-a-credential'
    at.secrets['GEMINI_MODEL'] = 'gemini-3.6-flash'
    at.run()
    at.text_input(key='login_password').set_value(TEST_PASSWORD)
    next(b for b in at.button if b.label == 'Đăng nhập').click().run()
    return at


def upload(text="Ngày họp: 13-09-2026\nNam: Tôi sẽ làm API."):
    return SimpleNamespace(name="M001.txt", getvalue=lambda: text.encode("utf-8"))


def response(payload):
    return json.dumps({key: payload[key] for key in (
        "meeting_id", "meeting_date", "meeting_date_evidence")} | {"items": [
            dict(item_id="ITEM001", source_excerpt=["Nam: Tôi sẽ làm API."],
                 content_type="task_candidate", description="Làm API", owners=["Nam"],
                 deadline_status="missing", commitment="explicit", depends_on=[])]})


def navigate(at, label):
    next(button for button in at.button if button.key == f"nav_{label}").click().run()


class AppTests(unittest.TestCase):
    def test_n8n_sends_final_json_only_on_click_and_handles_errors(self):
        from ui.staging import as_dict

        with patch("streamlit.file_uploader", return_value=upload()), patch.object(
                pipeline, "call_llm", side_effect=response), patch(
                "services.n8n_service.requests.post") as post:
            at = make_app()
            navigate(at, "Extraction Result")
            self.assertFalse(any(b.label == "Send to Task Workflow" for b in at.button))
            navigate(at, "Transcript")
            at.button[0].click().run()
            navigate(at, "Extraction Result")
            post.assert_not_called()
            final_json = as_dict(at.session_state["final_object"])
            result = requests.Response()
            result.status_code = 200
            result._content = b"accepted"
            post.return_value = result
            at.button(key="send_to_task_workflow").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.success[0].value, "Đã gửi dữ liệu sang n8n thành công.")
            post.assert_called_once_with(
                "http://localhost:5678/webhook/task-input",
                json=final_json, timeout=30, allow_redirects=False)
            at.run()
            self.assertEqual(post.call_count, 1)

            result.status_code = 500
            result._content = b"workflow failed"
            at.button(key="send_to_task_workflow").click().run()
            self.assertFalse(at.exception)
            self.assertIn("500", at.error[0].value)
            self.assertTrue(any(t.value == "workflow failed" for t in at.text))
            for error, message in (
                    (requests.ConnectionError(), "Không kết nối được n8n"),
                    (requests.Timeout(), "n8n không phản hồi")):
                post.side_effect = error
                at.button(key="send_to_task_workflow").click().run()
                self.assertFalse(at.exception)
                self.assertIn(message, at.error[0].value)
            self.assertEqual(as_dict(at.session_state["final_object"]), final_json)

    def test_friendly_errors_and_technical_detail_only_in_logs(self):
        from src.schema_validator import OutputValidationError
        cases = [
            (pipeline.DailyQuotaExceededError("API HTTP 429: quota exceeded; provider detail"),
             "Đã đạt giới hạn sử dụng API hôm nay. Vui lòng thử lại sau khi quota được reset hoặc kiểm tra API plan."),
            (RuntimeError("API HTTP 429: hết 5 lần retry; detail"),
             "Đã đạt giới hạn sử dụng API hiện tại. Vui lòng thử lại sau hoặc kiểm tra quota/API plan."),
            (RuntimeError("RESOURCE_EXHAUSTED: quota detail"),
             "Đã đạt giới hạn sử dụng API hiện tại. Vui lòng thử lại sau hoặc kiểm tra quota/API plan."),
            (RuntimeError("API HTTP 503: hết 5 lần retry; detail"),
             "Dịch vụ AI đang tạm thời quá tải. Vui lòng thử lại sau ít phút."),
            (RuntimeError("UNAVAILABLE: provider detail"),
             "Dịch vụ AI đang tạm thời quá tải. Vui lòng thử lại sau ít phút."),
            (OutputValidationError("Business validation thất bại: ITEM001 detail"),
             "Kết quả LLM không hợp lệ theo schema hoặc business rules. Vui lòng xem chi tiết ở tab Validation & JSON."),
            (RuntimeError("Unexpected internal detail"),
             "Đã xảy ra lỗi khi xử lý transcript. Vui lòng thử lại hoặc xem chi tiết trong Logs."),
        ]
        for error, message in cases:
            with self.subTest(error=str(error)), patch("streamlit.file_uploader", return_value=upload()), patch.object(
                    pipeline, "call_llm", side_effect=error):
                at = make_app()
                at.button[0].click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.error[0].value, message)
                detail = f"{type(error).__name__}: {error}"
                self.assertEqual(at.session_state["error_message"], detail)
                navigate(at, "Validation & JSON")
                logs = next(tab for tab in at.tabs if tab.label == "Logs")
                self.assertEqual(logs.error[0].value, detail)
                self.assertEqual(sum(element.value == detail for element in at.error), 1)
                # A subsequent successful run must clear both error messages.
                navigate(at, "Transcript")
                with patch.object(pipeline, "call_llm", side_effect=response):
                    at.button[0].click().run()
                self.assertIsNone(at.session_state["error_message"])
                self.assertIsNone(at.session_state["user_error_message"])
                self.assertFalse(at.error)

    def test_initial_screen_does_not_call_api(self):
        with patch.object(pipeline, "call_llm") as llm:
            at = make_app()
        self.assertFalse(at.exception)
        self.assertEqual([button.label for button in at.button[1:4]],
                         ["Transcript", "Kết quả trích xuất", "Kiểm tra JSON"])
        self.assertTrue(at.button[0].disabled)
        self.assertIsNone(at.date_input[0].value)
        llm.assert_not_called()

    def test_success_and_metadata_edit_clear_old_result(self):
        with patch("streamlit.file_uploader", return_value=upload()), patch.object(
                pipeline, "call_llm", side_effect=response) as llm:
            at = make_app()
            self.assertEqual(at.text_input[0].value, "M001")
            self.assertEqual(at.date_input[0].value.isoformat(), "2026-09-13")
            at.button[0].click().run()
            self.assertFalse(at.exception)
            navigate(at, "Extraction Result")
            self.assertEqual([metric.value for metric in at.metric], ["1", "1", "0", "0"])
            self.assertFalse(at.exception)
            self.assertTrue(any(t.value == 'Làm API' for t in at.text))
            navigate(at, "Validation & JSON")
            self.assertEqual([t.label for t in at.tabs], ["Raw JSON", "Validated Object", "Final JSON", "Logs"])
            self.assertEqual(len(at.json), 3)
            self.assertIsNotNone(at.session_state["validated_object"])
            self.assertIsNotNone(at.session_state["final_object"])
            navigate(at, "Transcript")
            at.text_input[0].set_value("M002").run()
            self.assertIsNone(at.session_state["final_object"])
            self.assertEqual(llm.call_count, 1)

    def test_failed_rerun_keeps_raw_but_clears_final(self):
        with patch("streamlit.file_uploader", return_value=upload()), patch.object(
                pipeline, "call_llm", side_effect=response):
            at = make_app()
            at.button[0].click().run()
            with patch.object(pipeline, "call_llm", return_value="broken JSON"):
                at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertIsNone(at.session_state["final_object"])
            self.assertEqual(at.session_state["raw_output"], "broken JSON")
            self.assertIn("JSON không hợp lệ", at.session_state["error_message"])
            self.assertEqual(at.session_state["pipeline_status"]["Decision Policy"], "Chưa chạy")

    def test_business_and_api_errors(self):
        def invalid_business(payload):
            data = json.loads(response(payload))
            data["items"][0]["depends_on"] = ["ITEM999"]
            return json.dumps(data)

        with patch("streamlit.file_uploader", return_value=upload("Nam: Tôi sẽ làm API.")), patch.object(
                pipeline, "call_llm", side_effect=invalid_business):
            at = make_app()
            self.assertIsNone(at.date_input[0].value)
            at.button[0].click().run()
            self.assertFalse(at.exception)
            status = at.session_state["pipeline_status"]
            self.assertEqual(status["Schema Validation"], "Thành công")
            self.assertEqual(status["Business Validation"], "Thất bại")
            with patch.object(pipeline, "call_llm", side_effect=RuntimeError("API unavailable")):
                at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertIsNone(at.session_state["raw_output"])
            self.assertEqual(at.session_state["pipeline_status"]["LLM Extraction"], "Thất bại")


if __name__ == "__main__":
    unittest.main()
