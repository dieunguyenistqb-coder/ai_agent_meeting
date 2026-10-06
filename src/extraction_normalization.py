"""Pre-policy normalization; audit stays outside the business models."""
from copy import deepcopy
from datetime import datetime, date
import json
import re
import logging
from difflib import get_close_matches

logger = logging.getLogger(__name__)
from deadline_merge_v2 import apply_deadline_resolution
from .schemas import RawMeetingOutput
from .source_grounding import transcript_turns, citation_matches, whitespace
from .schema_validator import OutputValidationError, parse_and_validate, validate_business_rules

HEADER = re.compile(r'^\s*Ngày họp\s*:[^\r\n]*', re.MULTILINE | re.IGNORECASE)


def prepare_transcript(transcript, fallback_date):
    if not HEADER.search(transcript) and fallback_date:
        try:
            day = date.fromisoformat(fallback_date)
        except (ValueError, TypeError):
            return transcript
        return f'Ngày họp: {day:%d-%m-%Y}\n\n{transcript}'
    return transcript


def transcript_meeting_date(transcript):
    headers = HEADER.findall(transcript)
    if len(headers) != 1:
        return None
    value = headers[0].split(':', 1)[1].strip()
    if not re.fullmatch(r'\d{2}-\d{2}-\d{4}', value):
        return None
    try:
        return datetime.strptime(value, '%d-%m-%Y').date().isoformat()
    except ValueError:
        return None


def normalize_extraction(raw, transcript, meeting_id, meeting_date_evidence=None, audit=None):
    # Structural validation only: deadline invariants are checked after resolution.
    data = parse_and_validate(raw, check_business=False).model_dump()
    original = deepcopy(data)
    diagnostics = []
    if audit is not None:
        audit.update(model_output=original, diagnostics=diagnostics)

    def diagnostic(kind, item_id, **details):
        entry = dict(meeting_id=meeting_id, item_id=item_id, kind=kind, **details)
        diagnostics.append(entry)
        logger.warning('Extraction diagnostic: %s', json.dumps(entry, ensure_ascii=False))
        return entry

    def fail(entry):
        error = OutputValidationError(json.dumps(entry, ensure_ascii=False))
        error.stage = 'Dedup / Source Validation'
        raise error

    seen, aliases, kept, by_id = {}, {}, [], {}
    for item in data['items']:
        fingerprint = json.dumps({k:v for k,v in item.items() if k != 'item_id'}, sort_keys=True, ensure_ascii=False)
        if item['item_id'] in by_id and by_id[item['item_id']] != fingerprint:
            fail(diagnostic('DUPLICATE', item['item_id'], canonical_item_id=item['item_id'],
                            reason='Cùng item_id nhưng nội dung khác nhau; không thể ánh xạ dependency an toàn.'))
        by_id[item['item_id']] = fingerprint
        if fingerprint in seen:
            canonical = seen[fingerprint]
            if item['item_id'] != canonical:
                aliases[item['item_id']] = canonical
            diagnostic('DUPLICATE', item['item_id'], canonical_item_id=canonical,
                       action='removed', reason='Nội dung giống hoàn toàn, giữ item canonical.')
        else:
            seen[fingerprint] = item['item_id']
            kept.append(item)
    turns = transcript_turns(transcript)
    lines = [f'{speaker}: {content}' if speaker else content for speaker, content in turns]
    mismatches = []
    for item in kept:
        item['depends_on'] = list(dict.fromkeys(aliases.get(dep, dep) for dep in item['depends_on']))
        for excerpt in item['source_excerpt']:
            normalized_excerpt = whitespace(excerpt)
            if not citation_matches(excerpt, turns):
                closest = get_close_matches(normalized_excerpt, lines, n=1, cutoff=0)
                mismatches.append(diagnostic('SOURCE_EXCERPT', item['item_id'],
                    source_excerpt=excerpt, closest_transcript_line=closest[0] if closest else None,
                    reason='Trích dẫn rỗng.' if not normalized_excerpt else
                    'Không khớp nguyên văn sau chuẩn hóa whitespace; có khác biệt từ ngữ, người nói hoặc dấu câu.'))
    mismatch_ids = {entry['item_id'] for entry in mismatches}
    meeting_date = transcript_meeting_date(transcript)
    item_audit = {}
    for item in kept:
        before = deepcopy(item)
        apply_deadline_resolution(item, meeting_date)
        item_audit[item['item_id']] = dict(
            source_validation_status='mismatch' if item['item_id'] in mismatch_ids else 'valid',
            source_validation_reason='source_excerpt không khớp transcript' if item['item_id'] in mismatch_ids else None,
            model_deadline=before['deadline'],
            model_deadline_status=before['deadline_status'], resolved_deadline=item['deadline'],
            resolved_deadline_status=item['deadline_status'],
            deadline_changed=(before['deadline'], before['deadline_status']) != (item['deadline'], item['deadline_status']))
    data.update(items=kept, meeting_id=meeting_id, meeting_date=meeting_date,
                meeting_date_evidence=meeting_date_evidence)
    if audit is not None:
        audit.update(model_output=original, duplicate_aliases=aliases, items=item_audit)
    normalized = RawMeetingOutput.model_validate(data)
    # Business rules must only see resolver output, never the model deadline.
    validate_business_rules(normalized, source_quarantine_ids=mismatch_ids)
    return normalized
