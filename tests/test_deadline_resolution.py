import json
import unittest
from src.pipeline import process_transcript
from src.extraction_normalization import prepare_transcript


class DeadlineResolutionTests(unittest.TestCase):
    def run_item(self, text, status='resolved', dependencies=None, transcript='Ngày họp: 20-09-2026\nPERSON1: làm việc', content='task_candidate'):
        item = dict(item_id='ITEM002', content_type=content, description='Việc',
            source_excerpt=['PERSON1: làm việc'], owners=['PERSON1'], commitment='explicit',
            deadline='2026-09-22', deadline_status=status, deadline_text=text, depends_on=dependencies or [])
        items = [item]
        if dependencies:
            items.insert(0, dict(item, item_id='ITEM001', deadline=None, deadline_status='missing', deadline_text=None, depends_on=[]))
        raw = json.dumps(dict(meeting_id='M1', meeting_date=None, items=items))
        audit = {}
        result = process_transcript(transcript, 'M1', '2026-09-20', extractor=lambda _:raw, audit=audit)
        return result, audit

    def test_rules_before_policy_and_audit(self):
        for text, status, deps, expected_date, expected_status in [
            ('chiều nay','resolved',[], '2026-09-20','date_resolved_time_ambiguous'),
            ('ngày mai','resolved',[], '2026-09-21','resolved'),
            ('chưa chốt','resolved',[],None,'missing'),
            ('tuần sau','resolved',[],None,'ambiguous'),
            (None,'event_based',['ITEM001'],None,'event_based'),
            (None,'event_based',[],None,'missing'),
            ('khi thuận tiện','resolved',[],None,'ambiguous')]:
            with self.subTest(text=text, status=status):
                (raw, validated, final), audit = self.run_item(text,status,deps)
                item = final.items[-1]
                self.assertEqual((item.deadline,item.deadline_status),(expected_date,expected_status))
                self.assertEqual(item.expected_decision,'human_review' if expected_status=='ambiguous' else 'confirmed')
                self.assertEqual(audit['items']['ITEM002']['model_deadline'],'2026-09-22')
                self.assertEqual(audit['items']['ITEM002']['resolved_deadline'], expected_date)
                self.assertTrue(audit['items']['ITEM002']['deadline_changed'])
                self.assertNotIn('_audit',item.model_dump())
                self.assertEqual(json.loads(raw)['items'][-1]['deadline'],'2026-09-22')

    def test_headers(self):
        text = prepare_transcript('PERSON1: làm việc','2026-09-20')
        self.assertEqual(text.count('Ngày họp:'),1)
        self.assertEqual(prepare_transcript(text,'2026-01-01'),text)
        (raw, validated, final), _ = self.run_item('ngày mai', transcript='Ngày họp: invalid\nPERSON1: làm việc')
        self.assertIsNone(final.meeting_date)
        self.assertEqual(final.items[0].expected_decision,'human_review')

    def test_dedup_and_quote_validation(self):
        from src.extraction_normalization import normalize_extraction
        (raw, _, _), _ = self.run_item('ngày mai')
        data = json.loads(raw)
        data['items'].append(dict(data['items'][0],item_id='ITEM003'))
        audit = {}
        normalized = normalize_extraction(json.dumps(data),'Ngày họp: 20-09-2026\nPERSON1: làm việc','M1',audit=audit)
        self.assertEqual(len(normalized.items),1)
        self.assertEqual(audit['duplicate_aliases'],{'ITEM003':'ITEM002'})
        mismatch_audit = {}
        normalize_extraction(raw,'Ngày họp: 20-09-2026\nkhác','M1',audit=mismatch_audit)
        self.assertEqual(mismatch_audit['items']['ITEM002']['source_validation_status'], 'mismatch')

    def test_non_tasks_unchanged_and_human_override(self):
        from deadline_merge_v2 import apply_deadline_resolution
        from copy import deepcopy
        from services.store import new_store, sync_meeting, task_key
        from services.review_service import ReviewService
        from ui.review_state import build_submission
        for content in ('decision', 'information', 'proposal'):
            item = dict(content_type=content, deadline='2026-09-22', deadline_status='resolved', deadline_text='ngày mai')
            before = deepcopy(item)
            self.assertEqual(apply_deadline_resolution(item,'2026-09-20'), before)
        (_, _, final), _ = self.run_item('tuần sau')
        state = dict(final_object=final, demo_store=new_store())
        sync_meeting(state['demo_store'], final)
        ReviewService(state['demo_store']).decide(task_key('M1','ITEM002'), 'edit',
            dict(description='Việc', owners=['PERSON1'], deadline='2026-10-01'))
        result = build_submission(state)
        self.assertEqual(result['items'][0]['deadline'], '2026-10-01')
        self.assertEqual(result['items'][0]['deadline_status'], 'resolved')

    def test_october_afternoon_business_sees_only_normalized_deadline(self):
        from unittest.mock import patch
        from src.schema_validator import validate_business_rules
        from src.decision_policy import apply_decision_policy
        item = dict(item_id='ITEM001', content_type='task_candidate', description='Merge code',
                    owners=['PERSON1'], source_excerpt=['PERSON1: Merge chiều nay.'],
                    commitment='explicit', deadline_text='chiều nay', deadline='2026-10-07',
                    deadline_status='resolved', depends_on=[])
        raw = json.dumps(dict(meeting_id='M1', meeting_date='2026-10-06', items=[item]))
        audit, calls = {}, []
        def business(data, **kwargs):
            calls.append('business')
            self.assertEqual(data.items[0].deadline, '2026-10-06')
            self.assertEqual(data.items[0].deadline_status, 'date_resolved_time_ambiguous')
            validate_business_rules(data, **kwargs)
        def policy(data):
            calls.append('policy')
            return apply_decision_policy(data)
        with patch('src.extraction_normalization.validate_business_rules', side_effect=business), patch('src.pipeline.apply_decision_policy', side_effect=policy):
            original, validated, final = process_transcript('Ngày họp: 06-10-2026\nPERSON1: Merge chiều nay.',
                'M1', '2026-10-06', extractor=lambda _:raw, audit=audit)
        self.assertEqual(calls, ['business', 'policy'])
        self.assertEqual(original, raw)
        self.assertEqual(final.items[0].deadline, validated.items[0].deadline)
        self.assertEqual(audit['items']['ITEM001'], dict(source_validation_status='valid', source_validation_reason=None, model_deadline='2026-10-07',
            model_deadline_status='resolved', resolved_deadline='2026-10-06',
            resolved_deadline_status='date_resolved_time_ambiguous', deadline_changed=True))
