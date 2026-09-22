import contextlib
import io
import json
import unittest
from unittest.mock import patch

from src import pipeline
from src.schema_validator import OutputValidationError
from src.schemas import RawMeetingOutput, FinalMeetingOutput


class PipelineTests(unittest.TestCase):
    def test_returns_outputs_preserves_metadata_without_print_or_write(self):
        evidence = {"evidence": "ngày họp", "reasoning": "provided"}
        raw = json.dumps(dict(meeting_id="M001", meeting_date="2026-09-13",
                              meeting_date_evidence=evidence, items=[]))
        output = io.StringIO()
        with patch.object(pipeline, "call_llm", return_value=raw) as llm, patch(
                "pathlib.Path.write_text") as write, patch("builtins.print") as print_mock, contextlib.redirect_stdout(output):
            text, validated, final = pipeline.process_transcript(
                "Nam: Xin chào.", "M001", "2026-09-13", evidence)
        self.assertEqual(text, raw)
        self.assertIsInstance(validated, RawMeetingOutput)
        self.assertIsInstance(final, FinalMeetingOutput)
        self.assertEqual(final.meeting_date_evidence, evidence)
        llm.assert_called_once_with(dict(transcript="Nam: Xin chào.", meeting_id="M001",
                                        meeting_date="2026-09-13", meeting_date_evidence=evidence))
        print_mock.assert_not_called()
        write.assert_not_called()
        self.assertEqual(output.getvalue(), "")

    def test_validation_failure_retains_raw_and_skips_policy(self):
        for raw in ("invalid JSON", '{"meeting_id": []}'):
            with self.subTest(raw=raw), patch.object(pipeline, "call_llm", return_value=raw), patch.object(
                    pipeline, "apply_decision_policy") as policy:
                with self.assertRaises(pipeline.PipelineError) as raised:
                    pipeline.process_transcript("Nam: Xin chào.", "M001", None)
                self.assertEqual(raised.exception.raw_output, raw)
                self.assertIsNone(raised.exception.validated_object)
                self.assertIsInstance(raised.exception.error, OutputValidationError)
                policy.assert_not_called()

    def test_api_failure_retains_original_error(self):
        error = RuntimeError("API unavailable")
        with patch.object(pipeline, "call_llm", side_effect=error), patch.object(
                pipeline, "parse_and_validate") as validator:
            with self.assertRaises(pipeline.PipelineError) as raised:
                pipeline.process_transcript("Nam: Xin chào.", "M001", None)
        self.assertIs(raised.exception.error, error)
        self.assertIsNone(raised.exception.raw_output)
        validator.assert_not_called()

    def test_policy_failure_retains_validated_object(self):
        raw = '{"meeting_id": "M001", "items": []}'
        with patch.object(pipeline, "call_llm", return_value=raw), patch.object(
                pipeline, "apply_decision_policy", side_effect=RuntimeError("policy error")):
            with self.assertRaises(pipeline.PipelineError) as raised:
                pipeline.process_transcript("Nam: Xin chào.", "M001", None)
        self.assertEqual(raised.exception.raw_output, raw)
        self.assertIsInstance(raised.exception.validated_object, RawMeetingOutput)

    def test_empty_transcript_does_not_call_api(self):
        with patch.object(pipeline, "call_llm") as llm:
            with self.assertRaises(pipeline.PipelineError) as raised:
                pipeline.process_transcript(" \n", "M001", None)
        self.assertIsInstance(raised.exception.error, ValueError)
        llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
