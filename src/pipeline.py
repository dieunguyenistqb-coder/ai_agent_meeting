"""Shared extraction pipeline; callers own presentation and persistence."""
import logging
import time

from .llm_client import call_llm
from .schema_validator import parse_and_validate
from .decision_policy import apply_decision_policy
from .schemas import RawMeetingOutput, FinalMeetingOutput

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class DailyQuotaExceededError(RuntimeError):
    """Non-retryable quota exhaustion; the original provider error is the cause."""


DAILY_QUOTA_MARKERS = (
    "resource_exhausted",
    "generate_content_free_tier_requests",
    "generaterequestsperdayperprojectpermodel-freetier",
    "quota exceeded",
    "exceeded your current quota",
)


def call_llm_with_retry(payload):
    """Initial call plus at most five retries for transient HTTP errors."""
    for attempt in range(6):
        try:
            return call_llm(payload)
        except Exception as exc:
            status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            # Apply the project's quota classification only to HTTP 429.
            detail = str(exc).casefold()
            if str(status) == "429" and any(marker in detail for marker in DAILY_QUOTA_MARKERS):
                raise DailyQuotaExceededError(
                    f"API HTTP 429: daily quota exhausted; {type(exc).__name__}: {exc}"
                ) from exc
            if str(status) not in {"429", "503"}:
                raise
            if attempt == 5:
                raise RuntimeError(
                    f"API HTTP {status}: hết 5 lần retry (6 lần gọi); "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            delay = 2 ** (attempt + 1)
            logger.info(f"[{payload['meeting_id']}] API {status}; retry {attempt + 1}/5 sau {delay}s")
            time.sleep(delay)


class PipelineError(Exception):
    """Failure with any completed outputs, so callers can retain raw evidence."""

    def __init__(self, error, raw_output=None, validated_object=None):
        super().__init__(str(error))
        self.error = error
        self.raw_output = raw_output
        self.validated_object = validated_object


def process_transcript(transcript: str, meeting_id: str, meeting_date: str | None,
                       meeting_date_evidence: dict | None = None
                       ) -> tuple[str, RawMeetingOutput, FinalMeetingOutput]:
    """Return (raw text, validated raw model, final model), without file writes.

    Raise PipelineError on failure; it retains the original error and any raw
    output/validated model completed before the failure. No policy runs unless
    validation succeeds. Metadata and transcript are passed through unchanged.
    """
    raw_output = None
    validated_object = None
    try:
        if not transcript.strip():
            raise ValueError("Transcript không được để trống")
        raw_output = call_llm_with_retry({
            "transcript": transcript, "meeting_id": meeting_id,
            "meeting_date": meeting_date, "meeting_date_evidence": meeting_date_evidence,
        })
        validated_object = parse_and_validate(raw_output)
        final_object = apply_decision_policy(validated_object)
        return raw_output, validated_object, final_object
    except Exception as exc:
        raise PipelineError(exc, raw_output, validated_object) from exc
