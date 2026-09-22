import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run
from src import pipeline
from src.schema_validator import OutputValidationError, parse_and_validate


def payload(**changes):
    item = dict(item_id="ITEM001", source_excerpt=["PERSON5: Tôi sẽ làm API."],
                content_type="task_candidate", description="Làm API", owners=["PERSON5"],
                deadline=None, deadline_status="missing", commitment="explicit", depends_on=[])
    item.update(changes)
    return dict(meeting_id="M001", meeting_date=None, meeting_date_evidence=None, items=[item])


class ValidationTests(unittest.TestCase):
    def test_business_failures_block_policy(self):
        cases = [
            (dict(content_type="decision", commitment="not_applicable"), "non_task_owners"),
            (dict(content_type="information", commitment="not_applicable"), "non_task_owners"),
            (dict(content_type="decision", owners=[]), "non_task_commitment"),
            (dict(content_type="information", owners=[]), "non_task_commitment"),
            (dict(deadline_status="resolved"), "resolved_deadline"),
            (dict(deadline="2026-09-01"), "missing_deadline"),
            (dict(depends_on=["ITEM999"]), "dependency_exists"),
            (dict(depends_on=["ITEM001"]), "no_self_dependency"),
            (dict(owners=["PERSON12"]), "owner_grounding"),
            (dict(source_excerpt=["PERSON50: Tôi sẽ làm API."]), "owner_grounding"),
            (dict(owners=["person5"]), "owner_grounding"),
            (dict(owners=[""]), "owner_grounding"),
            (dict(expected_decision="confirmed"), "extra_forbidden"),
            (dict(review_reason=None), "extra_forbidden"),
            (dict(confidence=0.9), "extra_forbidden"),
            (dict(content_type="task"), "literal_error"),
            (dict(owners="PERSON5"), "list_type"),
            (dict(depends_on="ITEM002"), "list_type"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "sample.txt"
            transcript.write_text("PERSON5: Tôi sẽ làm API.", encoding="utf-8")
            for changes, rule in cases:
                with self.subTest(rule=rule, changes=changes), patch.object(pipeline, "call_llm", return_value=json.dumps(payload(**changes))), patch.object(pipeline, "apply_decision_policy") as policy, patch.object(run, "RAW_DIR", root / "raw"), patch.object(run, "FINAL_DIR", root / "final"), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(OutputValidationError) as raised:
                        run.main(str(transcript), "M001", None)
                    self.assertIn("ITEM001", str(raised.exception))
                    self.assertIn(rule, str(raised.exception))
                    policy.assert_not_called()
                    self.assertTrue((root / "raw/sample_raw.json").exists())
                    self.assertFalse((root / "final/sample_final.json").exists())

    def test_valid_forward_dependency_and_exact_names(self):
        data = payload(owners=["Nguyễn An", "PERSON5"],
                       source_excerpt=["Lan: Nguyễn An và PERSON5 cùng làm API."],
                       depends_on=["ITEM002"])
        data["items"].append(payload(item_id="ITEM002", deadline_status="resolved",
                                     deadline="2026-09-01")["items"][0])
        self.assertEqual(len(parse_and_validate(json.dumps(data)).items), 2)

    def test_valid_non_tasks(self):
        for kind in ["decision", "information"]:
            parse_and_validate(json.dumps(payload(content_type=kind, owners=[],
                                                 commitment="not_applicable", deadline_status="not_applicable")))

    def test_root_extra_and_invalid_json(self):
        data = payload()
        data["unexpected"] = True
        with self.assertRaisesRegex(OutputValidationError, "meeting.*extra_forbidden"):
            parse_and_validate(json.dumps(data))
        with self.assertRaisesRegex(OutputValidationError, "json_parse"):
            parse_and_validate("not json")

    def test_multiple_errors_reported(self):
        with self.assertRaises(OutputValidationError) as raised:
            parse_and_validate(json.dumps(payload(owners=["Minh"], depends_on=["ITEM999"], deadline_status="resolved")))
        for rule in ["owner_grounding", "dependency_exists", "resolved_deadline"]:
            self.assertIn(rule, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
