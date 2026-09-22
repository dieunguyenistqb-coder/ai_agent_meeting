"""Run offline: python -m evaluation.evaluator --pred-dir ... --gt-dir ..."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from .metrics import FIELDS, calculate, flatten
from .error_analysis import ERROR_COLUMNS, analyze


def load_meetings(paths):
    meetings = {}
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict) or not isinstance(data.get('meeting_id'), str) or not data['meeting_id'].strip():
                raise ValueError('meeting_id phải là string không rỗng')
            if data['meeting_id'] in meetings:
                raise ValueError(f"Trùng meeting_id: {data['meeting_id']}")
            if not isinstance(data.get('items'), list):
                raise ValueError('items phải là array')
            ids = set()
            for item in data['items']:
                if not isinstance(item, dict):
                    raise ValueError('item phải là object')
                item_id = item.get('item_id')
                if not isinstance(item_id, str) or not item_id or item_id in ids:
                    raise ValueError('item_id thiếu/sai/trùng')
                ids.add(item_id)
                for field in FIELDS:
                    if field not in item:
                        raise ValueError(f'{item_id}: thiếu {field}')
                    value = item[field]
                    if field in ('owners', 'depends_on'):
                        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                            raise ValueError(f'{item_id}: {field} phải là array[string]')
                    elif not isinstance(value, str) and not (field == 'deadline' and value is None):
                        raise ValueError(f'{item_id}: {field} sai kiểu')
            meetings[data['meeting_id']] = data
        except (ValueError, OSError) as exc:
            raise ValueError(f'{path}: {exc}') from exc
    return meetings


def evaluate(predictions, ground_truth):
    all_pairs, errors, per_meeting = [], [], []
    for meeting_id in sorted(predictions.keys() | ground_truth.keys()):
        pred = {x['item_id']: x for x in predictions.get(meeting_id, {}).get('items', [])}
        gt = {x['item_id']: x for x in ground_truth.get(meeting_id, {}).get('items', [])}
        pairs = [(pred.get(key), gt.get(key)) for key in sorted(pred.keys() | gt.keys())]
        meeting_errors = analyze(meeting_id, pairs)
        errors.extend(meeting_errors)
        all_pairs.extend(pairs)
        status = ('missing_prediction' if meeting_id not in predictions else
                  'missing_ground_truth' if meeting_id not in ground_truth else 'matched')
        per_meeting.append(dict(meeting_id=meeting_id, status=status, gt_items=len(gt),
                                predicted_items=len(pred), error_count=len(meeting_errors),
                                **flatten(calculate(pairs))))
    summary = dict(
        meeting_count=len(per_meeting), ground_truth_meetings=len(ground_truth),
        prediction_meetings=len(predictions),
        missing_prediction_meetings=sorted(ground_truth.keys() - predictions.keys()),
        missing_ground_truth_meetings=sorted(predictions.keys() - ground_truth.keys()),
        metrics=calculate(all_pairs),
        errors_by_field={field: sum(row['field'] == field for row in errors)
                         for field in ('item',) + FIELDS},
        errors_by_type=dict(sorted(Counter(row['error_type'] for row in errors).items())),
        conventions=dict(matching='meeting_id then item_id; all items, not only task_candidate',
                         field_metrics='matched items only; macro F1 over union of observed labels',
                         set_metrics='micro counts across all items, including missing/extra; order ignored',
                         false_automatic_rate='false confirmed / all predicted confirmed; extra confirmed is false',
                         undefined='null in JSON, blank in CSV for zero denominator',
                         aggregation='pooled counts across meetings, not mean of meeting scores'))
    return summary, per_meeting, errors


def write_csv(path, columns, rows):
    with path.open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run_evaluation(pred_dir, gt_dir, output_dir):
    pred_dir, gt_dir, output_dir = map(Path, (pred_dir, gt_dir, output_dir))
    if not pred_dir.is_dir() or not gt_dir.is_dir():
        raise ValueError('pred-dir và gt-dir phải là folder tồn tại')
    gt_files = sorted(gt_dir.glob('*.json'))
    if not gt_files:
        raise ValueError('Không tìm thấy GT .json')
    predictions = load_meetings(sorted(pred_dir.glob('*/predicted_final.json')))
    truth = load_meetings(gt_files)
    summary, meetings, errors = evaluate(predictions, truth)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'evaluation_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    write_csv(output_dir / 'evaluation_summary.csv', ['metric', 'value'],
              [dict(metric=k, value=json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v)
               for k, v in flatten(summary).items()])
    columns = list(dict.fromkeys(key for row in meetings for key in row))
    write_csv(output_dir / 'per_meeting_results.csv', columns, meetings)
    serialized = [dict(row, predicted_value=json.dumps(row['predicted_value'], ensure_ascii=False),
                       ground_truth_value=json.dumps(row['ground_truth_value'], ensure_ascii=False))
                  for row in errors]
    write_csv(output_dir / 'error_analysis.csv', ERROR_COLUMNS, serialized)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pred-dir', default='outputs/batch')
    parser.add_argument('--gt-dir', default='data/ground_truth')
    parser.add_argument('--output-dir', default='outputs/evaluation')
    args = parser.parse_args()
    try:
        summary = run_evaluation(args.pred_dir, args.gt_dir, args.output_dir)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
