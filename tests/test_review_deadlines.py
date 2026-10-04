from copy import deepcopy
import unittest
from services.review_service import ReviewService
from services.store import new_store, sync_meeting, task_key
from ui.review_state import build_submission


class ReviewDeadlineTests(unittest.TestCase):
    def state(self, status, deadline):
        item = dict(item_id='ITEM001', description='Làm API', source_excerpt=['Nam: Làm API'],
                    owners=['Nam'], content_type='task_candidate', commitment='tentative',
                    deadline=deadline, deadline_status=status, depends_on=[],
                    expected_decision='human_review', review_reason='Review')
        data=dict(meeting_id='M1',meeting_date=None,meeting_date_evidence=None,items=[item])
        state={'final_object':data,'demo_store':new_store()}
        sync_meeting(state['demo_store'],data)
        return state

    def test_edit_deadline_cases_and_audit(self):
        for old, old_date, chosen, expected in [
            ('missing',None,None,'missing'),
            ('missing',None,'2026-10-08','resolved'),
            ('resolved','2026-10-08',None,'missing'),
            ('ambiguous',None,'2026-10-08','resolved'),
            ('conflict',None,'2026-10-08','resolved'),
            ('conflict',None,None,'conflict'),
        ]:
            with self.subTest(old=old, chosen=chosen):
                state=self.state(old,old_date)
                original=deepcopy(state['final_object'])
                key=task_key('M1','ITEM001')
                ReviewService(state['demo_store']).decide(key,'edit',
                    dict(description='Làm API',owners=['Nam'],deadline=chosen))
                result=build_submission(state)['items'][0]
                self.assertEqual(result['deadline'],chosen)
                self.assertEqual(result['deadline_status'],expected)
                stored=state['demo_store']['items'][key]
                self.assertEqual(stored['review_status'],'confirmed_by_human')
                self.assertEqual(state['final_object'],original)
                # Rebuild legacy history without the new derived field as well.
                stored['history'][-1]['changes'].pop('deadline_status',None)
                self.assertEqual(build_submission(state)['items'][0],result)

    def test_confirm_does_not_resolve_ambiguity(self):
        for status in ('ambiguous','conflict'):
            state=self.state(status,'2026-10-08')
            ReviewService(state['demo_store']).decide(task_key('M1','ITEM001'),'confirm')
            self.assertEqual(build_submission(state)['items'][0]['deadline_status'],status)
