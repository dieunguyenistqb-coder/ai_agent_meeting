from __future__ import annotations
from typing import Literal, Optional, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator

ContentType = Literal["task_candidate", "proposal", "decision", "information"]
DeadlineStatus = Literal[
    "resolved",
    "resolved_with_warning",
    "date_resolved_time_ambiguous",
    "event_based",
    "ambiguous",
    "missing",
    "conflict",
    "not_applicable",
]
Priority = Optional[Literal["high", "medium", "low"]]
Commitment = Literal["explicit", "tentative", "ambiguous", "not_applicable"]
ExpectedDecision = Literal["confirmed", "human_review", "not_task"]

class RawItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    source_excerpt: list[str]
    content_type: ContentType
    description: str
    owners: list[str]
    deadline: Optional[str] = None
    deadline_text: Optional[str] = None
    deadline_status: DeadlineStatus
    priority: Priority = None
    commitment: Commitment
    depends_on: list[str] = Field(default_factory=list)
    temporal_warning: Optional[str] = None

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        if not value.startswith("ITEM") or not value[4:].isdigit():
            raise ValueError("item_id phải có dạng ITEM001, ITEM002, ...")
        return value

class RawMeetingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    meeting_date: Optional[str] = None
    meeting_date_evidence: Optional[Any] = None
    items: list[RawItem] = Field(default_factory=list)

class FinalItem(RawItem):
    expected_decision: ExpectedDecision
    review_reason: Optional[str] = None

class FinalMeetingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    meeting_date: Optional[str] = None
    meeting_date_evidence: Optional[Any] = None
    items: list[FinalItem] = Field(default_factory=list)
