import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from evaluation.evaluator import evaluate, load_meetings, run_evaluation


def meeting():
    return {'meeting_id': 'M001', 'items': [dict(
        item_id='ITEM001', content_type='task_candidate', owners=['Nam'],
        deadline='2026-09-01', deadline_status='resolved', commitment='explicit',
        depends_on=['ITEM002'], expected_decision='confirmed')]}


class EvaluationTests(unittest.TestCase):
    def score(self, pred, gt):
        return evaluate({'M001': pred}, {'M001': gt})

    def test_perfect(self):
        summary, _, errors = self.score(meeting(), meeting())
        self.assertFalse(errors)
        for name in ('item_detection', 'owners', 'dependency'):
            self.assertEqual(summary['metrics'][name]['f1'], 1)
        self.assertEqual(summary['metrics']['content_type']['macro_f1'], 1)
        self.assertEqual(summary['metrics']['false_automatic_task_creation']['rate'], 0)

    def test_field_mismatches(self):
        for field, value in [('owners', ['Lan']), ('deadline', None),
                             ('commitment', 'tentative'), ('expected_decision', 'human_review'),
                             ('depends_on', ['ITEM003']), ('content_type', 'proposal'),
                             ('deadline_status', 'missing')]:
            with self.subTest(field=field):
                pred = meeting()
                pred['items'][0][field] = value
                summary, _, errors = self.score(pred, meeting())
                self.assertEqual(summary['metrics'][field]['accuracy'], 0)
                self.assertEqual([e['field'] for e in errors], [field])
                if field == 'owners':
                    self.assertEqual(summary['metrics']['owners']['f1'], 0)
                if field == 'depends_on':
                    self.assertEqual(summary['metrics']['dependency']['f1'], 0)

    def test_missing_and_extra_items(self):
        empty = dict(meeting_id='M001', items=[])
        for pred, gt, kind, fp, fn in [(empty, meeting(), 'missing_item', 0, 1),
                                     (meeting(), empty, 'extra_item', 1, 0)]:
            summary, _, errors = self.score(pred, gt)
            detection = summary['metrics']['item_detection']
            self.assertEqual((detection['fp'], detection['fn'], detection['f1']), (fp, fn, 0))
            self.assertEqual(errors[0]['error_type'], kind)
            self.assertIsNone(summary['metrics']['deadline']['accuracy'])
        self.assertEqual(self.score(meeting(), empty)[0]['metrics']['false_automatic_task_creation']['rate'], 1)

    def test_false_automatic_rate(self):
        gt = meeting()
        gt['items'][0]['expected_decision'] = 'human_review'
        self.assertEqual(self.score(meeting(), gt)[0]['metrics']['false_automatic_task_creation']['rate'], 1)

    def test_set_order_and_description_ignored(self):
        gt = meeting()
        gt['items'][0]['owners'] = ['Nam', 'Lan']
        pred = copy.deepcopy(gt)
        pred['items'][0].update(owners=['Lan', 'Nam'], description='different', source_excerpt=['different'])
        self.assertFalse(self.score(pred, gt)[2])

    def test_empty_denominators(self):
        empty = dict(meeting_id='M001', items=[])
        summary, _, _ = self.score(empty, empty)
        self.assertIsNone(summary['metrics']['item_detection']['f1'])
        self.assertIsNone(summary['metrics']['expected_decision']['macro_f1'])
        self.assertIsNone(summary['metrics']['false_automatic_task_creation']['rate'])

    def test_matching_meetings_and_micro_counts(self):
        gt = {'A': meeting(), 'B': meeting()}
        pred = {'A': meeting(), 'C': meeting()}
        summary, meetings, errors = evaluate(pred, gt)
        self.assertEqual(summary['metrics']['item_detection']['f1'], 0.5)
        self.assertEqual(summary['missing_prediction_meetings'], ['B'])
        self.assertEqual(summary['missing_ground_truth_meetings'], ['C'])
        self.assertEqual(len(errors), 2)
        self.assertEqual(len(meetings), 3)

    def test_files_outputs_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gt = root / 'gt'; pred = root / 'pred'; out = root / 'out'
            gt.mkdir(); (pred / 'different_filename').mkdir(parents=True)
            (gt / 'any_name.json').write_text(json.dumps(meeting()))
            saved = pred / 'different_filename/predicted_final.json'
            saved.write_text(json.dumps(meeting()))
            summary = run_evaluation(pred, gt, out)
            self.assertEqual(summary['metrics']['item_detection']['f1'], 1)
            self.assertEqual(len(list(out.iterdir())), 4)
            with (out / 'error_analysis.csv').open() as file:
                self.assertEqual(list(csv.DictReader(file)), [])
            bad = meeting(); bad['items'].append(copy.deepcopy(bad['items'][0]))
            saved.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, 'item_id'):
                load_meetings([saved])
            saved.write_text('invalid JSON')
            with self.assertRaises(ValueError):
                run_evaluation(pred, gt, out)


if __name__ == '__main__':
    unittest.main()
