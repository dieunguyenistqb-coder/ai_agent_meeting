"""Metrics with explicit counts and undefined-denominator handling."""

FIELDS = ('content_type', 'owners', 'deadline', 'deadline_status', 'commitment',
          'depends_on', 'expected_decision')
CATEGORICAL = ('content_type', 'deadline_status', 'commitment', 'expected_decision')


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def prf(tp, fp, fn):
    return dict(tp=tp, fp=fp, fn=fn, precision=ratio(tp, tp + fp),
                recall=ratio(tp, tp + fn), f1=ratio(2 * tp, 2 * tp + fp + fn))


def equal(field, predicted, truth):
    if field in ('owners', 'depends_on'):
        return set(predicted) == set(truth)
    return predicted == truth


def calculate(pairs):
    """Pairs include unmatched items as None; IDs have already been aligned."""
    matched = [(p, g) for p, g in pairs if p is not None and g is not None]
    result = {'item_detection': prf(len(matched),
              sum(g is None for p, g in pairs), sum(p is None for p, g in pairs))}
    for field in FIELDS:
        correct = sum(equal(field, p[field], g[field]) for p, g in matched)
        result[field] = dict(accuracy=ratio(correct, len(matched)), correct=correct, support=len(matched))
        if field in CATEGORICAL:
            labels = sorted({item[field] for pair in matched for item in pair})
            per_class = {}
            for label in labels:
                per_class[label] = prf(
                    sum(p[field] == label and g[field] == label for p, g in matched),
                    sum(p[field] == label and g[field] != label for p, g in matched),
                    sum(p[field] != label and g[field] == label for p, g in matched))
            result[field]['macro_f1'] = ratio(sum(v['f1'] for v in per_class.values()), len(labels))
            result[field]['per_class'] = per_class
    for field, name in (('owners', 'owners'), ('depends_on', 'dependency')):
        tp = fp = fn = 0
        for p, g in pairs:
            ps, gs = set(p[field]) if p else set(), set(g[field]) if g else set()
            tp += len(ps & gs)
            fp += len(ps - gs)
            fn += len(gs - ps)
        result.setdefault(name, {}).update(prf(tp, fp, fn))
    confirmed = [(p, g) for p, g in pairs if p and p['expected_decision'] == 'confirmed']
    false = sum(g is None or g['expected_decision'] != 'confirmed' for p, g in confirmed)
    result['false_automatic_task_creation'] = dict(rate=ratio(false, len(confirmed)),
                                                false_confirmed=false, predicted_confirmed=len(confirmed))
    return result


def flatten(data, prefix=''):
    rows = {}
    for key, value in data.items():
        name = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            rows.update(flatten(value, name))
        else:
            rows[name] = value
    return rows
