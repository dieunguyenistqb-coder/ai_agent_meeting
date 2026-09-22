# AGENTS.md

Before modifying this project:
1. Read `PROJECT_CONTEXT.md`.
2. Read `docs/schema_contract.md`.
3. Read `prompts/prompt_v1.txt` before changing LLM extraction logic.
4. Do not change schema field names or enum values unless explicitly requested.
5. Keep LLM extraction separate from Decision Policy.
6. LLM must not directly decide `confirmed`, `human_review`, or `not_task`.
7. `expected_decision` and `review_reason` are added by Decision Policy.
8. Do not add `confidence` to ground truth.
9. Never infer owner, deadline, or priority without transcript evidence.
10. `owners` and `depends_on` must always be arrays.
11. `temporal_warning` is optional and only for special temporal issues.
12. Preserve `meeting_id`, `meeting_date`, and `meeting_date_evidence`.
13. Preserve compatibility between ground truth and final predicted JSON.
14. Dataset target: 100 Vietnamese transcripts, 15–40 turns each.
15. No fine-tuning in the current scope; dataset is for evaluation/testing.
16. PostgreSQL is the Task Store.
17. n8n handles Human Review, Email, Calendar, scheduling, monitoring.
18. Streamlit is not part of the current MVP.
19. Task status enum: `not_started | in_progress | blocked | ready | done`.
20. Person 2 owns schema versioning, Decision Policy, LLM logic, offline evaluation, and E2E testing.
