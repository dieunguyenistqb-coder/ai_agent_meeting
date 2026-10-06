import json
import unittest
from src.extraction_normalization import normalize_extraction
from src.schema_validator import OutputValidationError


class SourceDiagnosticsTests(unittest.TestCase):
    def data(self):
        return dict(meeting_id='TEST01', items=[dict(item_id='ITEM001',
            content_type='task_candidate', description='Merge', owners=['PERSON2'],
            source_excerpt=['(PERSON2) Dạ, merge chiều nay.'], commitment='explicit',
            deadline='2026-10-07', deadline_status='resolved', deadline_text='chiều nay', depends_on=[])])

    def test_technical_whitespace_header_and_preserved_citation(self):
        data=self.data(); audit={}
        result=normalize_extraction(json.dumps(data), 'Ngày họp: 06-10-2026\r\n  (PERSON2)   Dạ,\r\n merge chiều nay.  ', 'TEST01', audit=audit)
        self.assertEqual(result.items[0].source_excerpt,data['items'][0]['source_excerpt'])
        self.assertEqual(result.items[0].deadline,'2026-10-06')

    def test_wrong_speaker_fails_with_diagnostic(self):
        audit={}
        normalize_extraction(json.dumps(self.data()),'Ngày họp: 06-10-2026\n(PERSON1) Dạ, merge chiều nay.','TEST01',audit=audit)
        self.assertEqual(audit['items']['ITEM001']['source_validation_status'], 'mismatch')
        d=audit['diagnostics'][0]
        self.assertEqual((d['meeting_id'],d['item_id'],d['kind']),('TEST01','ITEM001','SOURCE_EXCERPT'))
        self.assertIn('PERSON1',d['closest_transcript_line'])

    def test_safe_duplicate_removed_and_conflicting_id_rejected(self):
        data=self.data();data['items'].append(dict(data['items'][0]));audit={}
        transcript='Ngày họp: 06-10-2026\n(PERSON2) Dạ, merge chiều nay.'
        result=normalize_extraction(json.dumps(data),transcript,'TEST01',audit=audit)
        self.assertEqual(len(result.items),1)
        self.assertEqual(audit['diagnostics'][0]['action'],'removed')
        data['items'][1]['description']='Khác'
        with self.assertRaises(OutputValidationError): normalize_extraction(json.dumps(data),transcript,'TEST01')

    def test_quarantine_requires_human_confirmation(self):
        from src.pipeline import process_transcript
        from services.store import new_store, sync_meeting, task_key
        from services.review_service import ReviewService
        from ui.review_state import build_submission
        raw=json.dumps(self.data());audit={}
        original, validated, final=process_transcript('Ngày họp: 06-10-2026\n(PERSON1) Dạ, merge chiều nay.',
            'TEST01','2026-10-06',extractor=lambda _:raw,audit=audit)
        self.assertEqual(original,raw)
        self.assertEqual(final.items[0].source_excerpt,self.data()['items'][0]['source_excerpt'])
        self.assertEqual(final.items[0].deadline,'2026-10-06')
        self.assertEqual(final.items[0].expected_decision,'human_review')
        state=dict(final_object=final,extraction_audit=audit,demo_store=new_store())
        sync_meeting(state['demo_store'],final)
        with self.assertRaises(ValueError):build_submission(state)
        ReviewService(state['demo_store']).decide(task_key('TEST01','ITEM001'),'confirm')
        self.assertEqual(build_submission(state)['items'][0]['expected_decision'],'confirmed')
