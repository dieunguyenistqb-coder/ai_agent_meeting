from .schemas import RawMeetingOutput, FinalMeetingOutput, FinalItem

def apply_decision_policy(raw: RawMeetingOutput) -> FinalMeetingOutput:
    final_items: list[FinalItem] = []

    for item in raw.items:
        if item.content_type in {"decision", "information"}:
            decision = "not_task"
            reason = None

        elif item.content_type == "proposal":
            decision = "human_review"
            reason = "Nội dung mới là proposal, chưa được xác nhận."

        elif item.owners == []:
            decision = "human_review"
            reason = "Chưa xác định người phụ trách cụ thể."

        elif item.commitment != "explicit":
            decision = "human_review"
            reason = f"Commitment = {item.commitment}, chưa phải explicit."

        elif item.deadline_status in {"ambiguous", "conflict"}:
            decision = "human_review"
            if item.deadline_status == "ambiguous":
                reason = "Deadline có nhắc tới nhưng chưa đủ rõ."
            else:
                reason = "Có nhiều deadline mâu thuẫn, cần người dùng xác minh."

        else:
            decision = "confirmed"
            reason = None

        final_items.append(
            FinalItem(
                **item.model_dump(),
                expected_decision=decision,
                review_reason=reason,
            )
        )

    return FinalMeetingOutput(
        meeting_id=raw.meeting_id,
        meeting_date=raw.meeting_date,
        meeting_date_evidence=raw.meeting_date_evidence,
        items=final_items,
    )
