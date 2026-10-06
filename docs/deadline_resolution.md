# Deadline normalization before Decision Policy

`src.pipeline.process_transcript` prepares the transcript header before inference.
If no `Ngày họp:` header exists, a valid request/form ISO date is inserted once as
`Ngày họp: DD-MM-YYYY`. An existing malformed header is never replaced.
After structural JSON parsing, `src.extraction_normalization.normalize_extraction`
removes exact duplicate item content (excluding item_id), remaps dependencies to
retained IDs, validates each source excerpt as a verbatim substring, parses the
header date, and invokes the supplied `deadline_merge_v2.apply_deadline_resolution`.
Different content is not merged; duplicate IDs are rejected rather than overwritten.
Final business validation precedes the unchanged Decision Policy.

The resolver file is copied unchanged from the supplied deadline_merge_v2.py.
Only task_candidate deadline/status fields are resolved. Human edits and submission
rebuild never invoke the resolver.

Original raw output remains unchanged. Callers may pass an `audit` dictionary to
process_transcript. Streamlit stores it as `session_state.extraction_audit`, reset
on a new extraction. It contains original model_output, duplicate_aliases, and
per-item model_deadline/model_deadline_status/resolved_deadline/
resolved_deadline_status/deadline_changed. This dictionary is not sent to n8n.

Qwen HTTP payload is now `{ "transcript": "..." }`; meeting_date is no longer
sent as a separate field. The external FastAPI server must accept this payload
and construct its user prompt from `TRANSCRIPT:\n...` only. That server is not
part of this repository; its prompt and request schema cannot be updated here.
Timeout remains 300 seconds, with no fallback or automatic retries.

Source mismatch handling: citation text remains untouched. Per-item audit records
source_validation_status=mismatch and a reason. The shared pipeline runs the
semantic policy for all items, then requires human_review for every mismatched
item. The UI shows a warning stage and the original diagnostic. Owner grounding
for quarantined items is checked when validating the human confirmation; it is
not waived by confirmation. Other business rules still run. Final submission remains blocked until review is complete.
JSON/schema errors and conflicting content sharing an item_id remain fatal.
