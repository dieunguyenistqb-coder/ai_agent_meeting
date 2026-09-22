"""Field-level differences; no business decisions are recomputed."""
from .metrics import FIELDS, equal

ERROR_COLUMNS = ['meeting_id', 'predicted_item_id', 'ground_truth_item_id', 'field',
                 'predicted_value', 'ground_truth_value', 'error_type']


def analyze(meeting_id, pairs):
    errors = []
    for p, g in pairs:
        base = dict(meeting_id=meeting_id, predicted_item_id=p['item_id'] if p else None,
                    ground_truth_item_id=g['item_id'] if g else None)
        if p is None or g is None:
            errors.append(dict(base, field='item', predicted_value=p, ground_truth_value=g,
                               error_type='missing_item' if p is None else 'extra_item'))
        else:
            for field in FIELDS:
                if not equal(field, p[field], g[field]):
                    errors.append(dict(base, field=field, predicted_value=p[field],
                                       ground_truth_value=g[field], error_type='field_mismatch'))
    return errors
