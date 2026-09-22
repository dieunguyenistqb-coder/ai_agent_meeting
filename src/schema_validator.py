import json
import re
from pydantic import ValidationError
from .schemas import RawMeetingOutput


class OutputValidationError(ValueError):
    """Output không hợp lệ; không được chuyển sang Decision Policy."""


def validate_business_rules(raw: RawMeetingOutput) -> None:
    errors = []
    item_ids = {item.item_id for item in raw.items}
    for index, item in enumerate(raw.items):
        def fail(rule: str, message: str):
            errors.append(f"items[{index}] ({item.item_id}) [{rule}]: {message}")

        if item.content_type in {"decision", "information"}:
            if item.owners:
                fail("non_task_owners", "decision/information phải có owners=[]")
            if item.commitment != "not_applicable":
                fail("non_task_commitment", "decision/information phải có commitment=not_applicable")
        if item.deadline_status == "resolved" and item.deadline is None:
            fail("resolved_deadline", "resolved phải có deadline khác null")
        if item.deadline_status == "missing" and item.deadline is not None:
            fail("missing_deadline", "missing phải có deadline=null")
        for dependency in item.depends_on:
            if dependency not in item_ids:
                fail("dependency_exists", f"depends_on reference không tồn tại: {dependency!r}")
            if dependency == item.item_id:
                fail("no_self_dependency", "item không được phụ thuộc chính nó")
        for owner in item.owners:
            # Match literal, case-sensitive Unicode names/labels, not PERSON5 in PERSON50.
            pattern = rf"(?<!\w){re.escape(owner)}(?!\w)"
            if not owner.strip() or not any(re.search(pattern, excerpt) for excerpt in item.source_excerpt):
                fail("owner_grounding", f"owner {owner!r} không xuất hiện đúng tên/nhãn trong source_excerpt")
    if errors:
        raise OutputValidationError("Business validation thất bại:\n" + "\n".join(errors))


def parse_and_validate(raw_text: str) -> RawMeetingOutput:
    """
    Parse output LLM và validate đúng schema.
    Pydantic sẽ báo lỗi nếu:
    - thiếu field bắt buộc
    - enum sai
    - owners/depends_on không phải list
    - có field lạ
    """
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise OutputValidationError(
            f"meeting [json_parse]: JSON không hợp lệ tại dòng {exc.lineno}, cột {exc.colno}: {exc.msg}"
        ) from exc
    try:
        raw = RawMeetingOutput.model_validate(data)
    except ValidationError as exc:
        errors = []
        for error in exc.errors():
            location = error["loc"]
            label = "meeting"
            if len(location) >= 2 and location[0] == "items" and isinstance(location[1], int):
                index = location[1]
                item = data["items"][index]
                item_id = item.get("item_id", "thiếu item_id") if isinstance(item, dict) else "item không hợp lệ"
                label = f"items[{index}] ({item_id})"
            field = ".".join(map(str, location)) or "root"
            errors.append(f"{label} [{error['type']}] {field}: {error['msg']}")
        raise OutputValidationError("Schema validation thất bại:\n" + "\n".join(errors)) from exc
    validate_business_rules(raw)
    return raw
