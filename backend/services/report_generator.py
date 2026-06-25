"""Structured training report generation."""

from typing import Any

from services.case_types import (
    get_case_id,
    get_standard_final_area,
    get_standard_final_level,
    get_standard_initial_area,
    get_standard_initial_level,
)
from services.triage_rule_engine import generate_rule_basis


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

    feedback = case_data.get("dynamic_feedback") or case_data.get("feedback") or {}
    correct_points = feedback.get("correct_points") or []
    incorrect_points = _build_incorrect_points(record, serious_error_result)
    suggestions = feedback.get("recommended_remediation") or feedback.get("improvement_suggestions") or []

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
        "reassessment_on_time": state.get("reassessment_on_time", False) or (state.get("reassessment_completed", False) and not state.get("reassessment_overdue", False)),
        "reassessment_reasonable": _reassessment_interval_reasonable(init_decision),
        "deterioration_recognized": bool(state.get("deteriorated") and any(a.get("action_type") == "reassess" for a in student_actions)),
        "triage_upgraded": _has_upgrade(student_initial_level, student_final_level),
        "doctor_notified": bool(record.get("notification_events")),
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
    if "notify_doctor" not in actions and (record.get("timeline_state") or {}).get("deteriorated"):
        points.append("Doctor was not notified after deterioration")
    return points


def _recommended_training(incorrect_points: list[str], suggestions: list[str]) -> list[str]:
    if suggestions:
        return suggestions
    if incorrect_points:
        return ["Reassessment timing", "Dynamic vital-sign interpretation", "Retriage documentation"]
    return ["Maintain current dynamic triage workflow practice"]


def _reassessment_interval_reasonable(init_decision: dict[str, Any] | None) -> bool:
    if not init_decision:
        return False
    minutes = init_decision.get("reassessment_minutes")
    return isinstance(minutes, int) and 0 < minutes <= 30


def _has_upgrade(from_level: str, to_level: str) -> bool:
    rank = {"Ⅰ级": 1, "Ⅱ级": 2, "Ⅲ级": 3, "Ⅳ级": 4}
    return bool(from_level and to_level and rank.get(to_level, 5) < rank.get(from_level, 5))

