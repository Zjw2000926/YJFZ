"""Structured training report generation."""

from typing import Any

from services.case_types import (
    get_case_id,
    get_standard_final_area,
    get_standard_final_level,
    get_standard_initial_area,
    get_standard_initial_level,
    get_timeline_events,
    is_dynamic_case,
)
from services.triage_rule_engine import generate_rule_basis


def event_indicates_deterioration(event: dict[str, Any] | None) -> bool:
    """Return True for timeline events that should be treated as clinical worsening."""
    if not event:
        return False
    event_type = str(event.get("event_type") or "").lower()
    if event_type in {
        "deterioration",
        "critical_change",
        "symptom_worsening",
        "time_elapsed_without_reassessment",
    }:
        return True
    if event.get("severe_error_if_ignored"):
        return True
    if event.get("standard_level_after_event"):
        return True
    return False


def record_has_triggered_deterioration(record: dict[str, Any]) -> bool:
    """Infer deterioration from timeline flags and triggered events, not one field only."""
    state = record.get("timeline_state") or {}
    if state.get("deteriorated"):
        return True
    for event in state.get("timeline_events") or []:
        if event.get("triggered") and event_indicates_deterioration(event):
            return True
    return False


def student_recognized_deterioration(record: dict[str, Any]) -> bool:
    """A deterioration is recognized when the student reassesses, upgrades, or notifies."""
    if not record_has_triggered_deterioration(record):
        return False
    actions = {a.get("action_type") for a in record.get("student_actions") or []}
    if actions.intersection({"reassess", "upgrade_triage", "notify_doctor"}):
        return True
    return any((d.get("decision_type") == "reassessment") for d in record.get("triage_decisions") or [])


def generate_training_report(
    record: dict[str, Any],
    case_data: dict[str, Any],
    section_scores: dict[str, Any] | None = None,
    serious_error_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = record.get("timeline_state") or {}
    triage_decisions = record.get("triage_decisions") or []
    student_actions = record.get("student_actions") or []
    vital_log = record.get("vital_measurement_log") or []
    notes = record.get("notes") or []

    init_decision = next((d for d in triage_decisions if d.get("decision_type") == "initial"), None)
    reassessment_decisions = [d for d in triage_decisions if d.get("decision_type") == "reassessment"]
    final_decision = reassessment_decisions[-1] if reassessment_decisions else init_decision

    student_initial_level = (init_decision or {}).get("level") or ""
    student_initial_area = (init_decision or {}).get("area") or ""
    student_final_level = (final_decision or {}).get("level") or record.get("final_level_selected") or ""
    student_final_area = (final_decision or {}).get("area") or record.get("final_zone_selected") or ""

    timeline_nodes = generate_timeline_review(record, case_data)
    action_review = generate_action_review(record)
    case_is_dynamic = is_dynamic_case(case_data)
    deterioration_triggered = record_has_triggered_deterioration(record)
    reassessment_applicable = _reassessment_applicable(record, case_data)
    upgrade_applicable = _upgrade_applicable(record, case_data)
    doctor_required = _doctor_notification_required(record, case_data)
    doctor_notified = _doctor_notified(record, timely=deterioration_triggered)

    feedback = case_data.get("dynamic_feedback") or case_data.get("feedback") or {}
    correct_points = feedback.get("correct_points") or []
    incorrect_points = _build_incorrect_points(record, serious_error_result)
    suggestions = _clean_training_suggestions(
        feedback.get("recommended_remediation") or feedback.get("improvement_suggestions") or []
    )

    report = {
        "case_info": {
            "case_id": get_case_id(case_data),
            "case_name": case_data.get("display_name") or case_data.get("title") or "",
            "category": case_data.get("category", ""),
            "difficulty": case_data.get("difficulty"),
            "patient_profile": case_data.get("patient_profile") or {},
        },
        "student_info": {
            "student_id": record.get("user_id"),
            "student_name": record.get("user_display_name", ""),
        },
        "training_mode": record.get("mode", "practice"),
        "case_type": "dynamic" if case_is_dynamic else "static",
        "is_dynamic_case": case_is_dynamic,
        "reassessment_applicable": reassessment_applicable,
        "deterioration_applicable": case_is_dynamic and deterioration_triggered,
        "upgrade_applicable": upgrade_applicable,
        "doctor_notification_required": doctor_required,
        "standard_initial_level": get_standard_initial_level(case_data),
        "standard_initial_area": get_standard_initial_area(case_data),
        "standard_final_level": get_standard_final_level(case_data),
        "standard_final_area": get_standard_final_area(case_data),
        "student_initial_level": student_initial_level,
        "student_initial_area": student_initial_area,
        "student_final_level": student_final_level,
        "student_final_area": student_final_area,
        "timeline_nodes": timeline_nodes,
        "patient_state_timeline": timeline_nodes,
        "student_actions": action_review,
        "action_timeline": action_review,
        "vital_measurement_log": vital_log,
        "vital_sign_timeline": vital_log,
        "triage_decisions": triage_decisions,
        "reassessment_on_time": (
            state.get("reassessment_on_time", False)
            or (state.get("reassessment_completed", False) and not state.get("reassessment_overdue", False))
        ) if reassessment_applicable else None,
        "reassessment_reasonable": _reassessment_interval_reasonable(init_decision, case_data),
        "deterioration_recognized": student_recognized_deterioration(record) if (case_is_dynamic and deterioration_triggered) else None,
        "triage_upgraded": _has_upgrade(student_initial_level, student_final_level) if upgrade_applicable else None,
        "doctor_notified": doctor_notified,
        "notification_events": record.get("notification_events") or [],
        "notes": notes,
        "score_breakdown": generate_score_breakdown(section_scores or {}),
        "correct_points": correct_points,
        "incorrect_points": incorrect_points,
        "standard_basis": generate_rule_basis(case_data, record),
        "improvement_suggestions": suggestions,
        "recommended_training": _recommended_training(incorrect_points, suggestions),
        "serious_error_summary": generate_serious_error_summary(serious_error_result or {}),
        "stage_history": state.get("stage_history") or [],
    }
    return report


def generate_timeline_review(record: dict[str, Any], case_data: dict[str, Any]) -> list[dict[str, Any]]:
    state = record.get("timeline_state") or {}
    nodes = [{
        "minute": 0,
        "label": "T0",
        "event": (case_data.get("initial_exposure") or {}).get("chief_complaint", ""),
        "patient_state_id": "T0_initial",
        "stage": "ARRIVAL",
    }]
    for event in state.get("timeline_events") or []:
        if event.get("triggered"):
            nodes.append({
                "minute": event.get("scheduled_minute", 0),
                "label": f"T{event.get('scheduled_minute', 0)}",
                "event": event.get("event_description") or event.get("patient_expression") or "",
                "event_type": event.get("event_type", ""),
                "patient_state_id": event.get("patient_state_id", ""),
                "requires_reassessment": event.get("requires_reassessment", False),
            })
    return nodes


def generate_action_review(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        "action_type": action.get("action_type", ""),
        "minute": action.get("simulation_minute", 0),
        "detail": action.get("detail") or {},
        "is_key_action": action.get("is_key_action", False),
        "is_required": action.get("is_required"),
        "is_correct": action.get("is_correct"),
        "is_late": action.get("is_late", False),
        "score_delta": action.get("score_delta"),
        "feedback": action.get("feedback", ""),
    } for action in record.get("student_actions") or []]


def generate_score_breakdown(section_scores: dict[str, Any]) -> dict[str, Any]:
    return section_scores


def generate_serious_error_summary(serious_error_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "serious_error_triggered": serious_error_result.get("serious_error_triggered", False),
        "serious_error_codes": serious_error_result.get("serious_error_codes", []),
        "serious_error_reasons": serious_error_result.get("serious_error_reasons", []),
        "final_result": serious_error_result.get("final_result", "pass"),
        "override_reason": serious_error_result.get("override_reason", ""),
    }


def _build_incorrect_points(record: dict[str, Any], serious_error_result: dict[str, Any] | None) -> list[str]:
    points = []
    if serious_error_result:
        points.extend(serious_error_result.get("serious_error_reasons") or [])
    actions = [a.get("action_type") for a in record.get("student_actions") or []]
    if "record_note" not in actions:
        points.append("Missing record note")
    if "notify_doctor" not in actions and record_has_triggered_deterioration(record):
        points.append("Doctor was not notified after deterioration")
    if record_has_triggered_deterioration(record) and not student_recognized_deterioration(record):
        points.append("Deterioration was not reassessed or recognized")
    return points


def _recommended_training(incorrect_points: list[str], suggestions: list[str]) -> list[str]:
    suggestions = _clean_training_suggestions(suggestions)
    if suggestions:
        return suggestions
    if incorrect_points:
        return ["Reassessment timing", "Dynamic vital-sign interpretation", "Retriage documentation"]
    return ["Maintain current dynamic triage workflow practice"]


def _clean_training_suggestions(suggestions: Any) -> list[str]:
    if isinstance(suggestions, str):
        raw_items = [suggestions]
    elif isinstance(suggestions, list):
        raw_items = [str(item) for item in suggestions if item]
    else:
        raw_items = []

    blocked_terms = (
        "输出限制",
        "不写治疗处方",
        "不写药物剂量",
        "不写成医生诊断题",
        "不让虚拟患者",
        "不省略评分细则",
        "不使用真实患者隐私",
        "评分标准过于笼统",
        "提示词",
        "LLM",
        "token",
    )
    cleaned: list[str] = []
    seen = set()
    for item in raw_items:
        text = item.strip(" -，,。；;")
        if not text or any(term in text for term in blocked_terms):
            continue
        if text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def _reassessment_interval_reasonable(init_decision: dict[str, Any] | None, case_data: dict[str, Any] | None = None) -> bool:
    if not init_decision:
        return False
    minutes = init_decision.get("reassessment_minutes")
    return isinstance(minutes, int) and 0 < minutes <= _expected_reassessment_minutes(case_data or {})


def _has_upgrade(from_level: str, to_level: str) -> bool:
    rank = {"Ⅰ级": 1, "Ⅱ级": 2, "Ⅲ级": 3, "Ⅳ级": 4}
    return bool(from_level and to_level and rank.get(to_level, 5) < rank.get(from_level, 5))


def _reassessment_applicable(record: dict[str, Any], case_data: dict[str, Any]) -> bool:
    """Only dynamic/waiting cases should be judged for on-time reassessment."""
    if not is_dynamic_case(case_data):
        return False
    state = record.get("timeline_state") or {}
    if state.get("reassessment_due") or state.get("reassessment_completed") or state.get("reassessment_overdue"):
        return True
    for event in state.get("timeline_events") or []:
        if event.get("requires_reassessment") or event_indicates_deterioration(event):
            return True
    for event in get_timeline_events(case_data):
        if event.get("requires_reassessment") or event_indicates_deterioration(event):
            return True
    return False


def _upgrade_applicable(record: dict[str, Any], case_data: dict[str, Any]) -> bool:
    """Retriage upgrade is a dynamic deterioration concept, not a static-case penalty."""
    if not is_dynamic_case(case_data):
        return False
    if record_has_triggered_deterioration(record):
        return True
    return bool(
        get_standard_initial_level(case_data)
        and get_standard_final_level(case_data)
        and get_standard_initial_level(case_data) != get_standard_final_level(case_data)
    )


def _doctor_notification_required(record: dict[str, Any], case_data: dict[str, Any]) -> bool:
    standard_level = get_standard_final_level(case_data) or get_standard_initial_level(case_data)
    if standard_level in {"Ⅰ级", "Ⅱ级"}:
        return True
    if record_has_triggered_deterioration(record):
        return True
    disposition = case_data.get("standard_answer", {}).get("disposition") or []
    return any("通知医生" in str(item) or "抢救" in str(item) for item in disposition)


def _expected_reassessment_minutes(case_data: dict[str, Any]) -> int:
    timeline = (case_data or {}).get("dynamic_timeline") or {}
    initial_stage = timeline.get("initial_stage") or {}
    if isinstance(initial_stage, dict):
        try:
            value = int(initial_stage.get("reassessment_due_minutes") or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    level = get_standard_initial_level(case_data or {})
    rank = {"Ⅰ级": 1, "Ⅱ级": 2, "Ⅲ级": 3, "Ⅳ级": 4}.get(level, 4)
    if rank <= 1:
        return 0
    if rank == 2:
        return 10
    if rank == 3:
        return 30
    return 60


def _record_deterioration_minute(record: dict[str, Any]) -> int | None:
    minutes = []
    for event in (record.get("timeline_state") or {}).get("timeline_events") or []:
        if event.get("triggered") and event_indicates_deterioration(event):
            try:
                minutes.append(int(event.get("scheduled_minute") or 0))
            except (TypeError, ValueError):
                pass
    return min(minutes) if minutes else None


def _doctor_notified(record: dict[str, Any], timely: bool = False) -> bool:
    deterioration_minute = _record_deterioration_minute(record) if timely else None

    def is_timely(minute: Any) -> bool:
        if deterioration_minute is None:
            return True
        try:
            return int(minute or 0) >= deterioration_minute
        except (TypeError, ValueError):
            return False

    if record.get("notification_events"):
        if not timely or any(is_timely(item.get("simulation_minute")) for item in record.get("notification_events") or []):
            return True
    final_disposition = record.get("final_disposition") or []
    if not timely and any("notify_doctor" == str(item) or "通知医生" in str(item) or "医生" in str(item) for item in final_disposition):
        return True
    for decision in record.get("triage_decisions") or []:
        if decision.get("notify_doctor") and is_timely(decision.get("simulation_minute")):
            return True
    for action in record.get("student_actions") or []:
        if action.get("action_type") == "notify_doctor" and is_timely(action.get("simulation_minute")):
            return True
    return False
