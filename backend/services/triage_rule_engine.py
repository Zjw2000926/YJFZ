"""Stable triage rule helpers and serious-error detection."""

from typing import Any

from services.triage_rules.engine import evaluate as evaluate_rules
from services.triage_rules.models import LEVEL_RANK


def evaluate_minimum_triage_level(case_data: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_rules(case_data, record)
    return result.to_dict() if hasattr(result, "to_dict") else result


def detect_under_triage(student_level: str, standard_level: str) -> bool:
    return LEVEL_RANK.get(student_level, 4) > LEVEL_RANK.get(standard_level, 4)


def detect_over_triage(student_level: str, standard_level: str) -> bool:
    return LEVEL_RANK.get(student_level, 4) < LEVEL_RANK.get(standard_level, 4)


def map_to_area(level: str) -> str:
    rank = LEVEL_RANK.get(level, 4)
    if rank <= 2:
        return "红区"
    if rank == 3:
        return "黄区"
    return "绿区"


def map_to_esi_or_ctas(level: str) -> dict[str, int]:
    rank = LEVEL_RANK.get(level, 4)
    return {"esi": rank, "ctas": rank}


def generate_rule_basis(case_data: dict[str, Any], record: dict[str, Any]) -> str:
    feedback = case_data.get("dynamic_feedback") or {}
    if feedback.get("reason_for_triage_level"):
        return feedback["reason_for_triage_level"]
    standard = case_data.get("standard_answer") or {}
    return standard.get("triage_basis") or standard.get("reason_for_triage_level") or ""


def detect_serious_errors(case_data: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    errors = []
    state = record.get("timeline_state") or {}
    triage_decisions = record.get("triage_decisions") or []
    notifications = record.get("notification_events") or []
    vital_log = record.get("vital_measurement_log") or []

    init_decision = next((d for d in triage_decisions if d.get("decision_type") == "initial"), None)
    reassessment_decisions = [d for d in triage_decisions if d.get("decision_type") == "reassessment"]
    student_initial = (init_decision or {}).get("level")
    final_decision = reassessment_decisions[-1] if reassessment_decisions else init_decision or {}
    student_final = final_decision.get("level")
    student_final_area = final_decision.get("area") or record.get("final_zone_selected")

    standard_initial = case_data.get("standard_initial_triage_level") or (case_data.get("standard_answer") or {}).get("triage_level")
    standard_final = case_data.get("standard_final_triage_level") or standard_initial

    if standard_initial == "Ⅰ级" and LEVEL_RANK.get(student_initial or "Ⅳ级", 4) >= 3:
        errors.append(_error("LEVEL1_UNDER_TRIAGE", "Ⅰ级患者被判为Ⅲ级或Ⅳ级", True))
    if standard_final == "Ⅱ级" and LEVEL_RANK.get(student_final or "Ⅳ级", 4) >= 4:
        errors.append(_error("LEVEL2_TO_IV", "Ⅱ级高危患者被判为Ⅳ级", True))

    triggered_det = [e for e in state.get("timeline_events", []) if e.get("triggered") and _event_indicates_deterioration(e)]
    det_minute = min([int(e.get("scheduled_minute") or 0) for e in triggered_det], default=None)
    reassessed = bool(state.get("reassessment_completed")) or any(a.get("action_type") == "reassess" for a in record.get("student_actions", []))
    upgraded = bool(student_initial and student_final and LEVEL_RANK.get(student_final, 4) < LEVEL_RANK.get(student_initial, 4))
    reaches_standard_final = bool(student_final and LEVEL_RANK.get(student_final, 4) <= LEVEL_RANK.get(standard_final, 4))
    timely_notification = _timely_doctor_notification(record, det_minute)

    if student_final == "Ⅰ级" and not _is_red_area(student_final_area):
        errors.append(_error("LEVEL_AREA_MISMATCH_LEVEL1", "Ⅰ级分诊必须安排红区/抢救区，不能安排黄区或绿区候诊", True))
    if LEVEL_RANK.get(standard_final or "", 4) <= 2 and _is_green_waiting_area(student_final_area):
        errors.append(_error("HIGH_RISK_GREEN_WAITING_AREA", "Ⅰ/Ⅱ级高危患者不能安排普通绿区候诊", True))

    for configured in case_data.get("dynamic_severe_errors", []):
        code = configured.get("code", "")
        message = configured.get("message", code)
        critical = configured.get("critical_fail", True)
        deduction = configured.get("deduction", 0)
        if code == "NO_REASSESS_AFTER_WORSENING" and triggered_det and not reassessed:
            errors.append(_error(code, message, critical, deduction))
        elif code == "NO_UPGRADE_AFTER_WORSENING" and triggered_det and reassessed and (not upgraded or not reaches_standard_final):
            errors.append(_error(code, message, critical, deduction))
        elif code == "NO_DOCTOR_NOTIFICATION" and triggered_det and upgraded and not timely_notification:
            errors.append(_error(code, message, critical, deduction))
        elif code == "T30_VITALS_NOT_REMEASURED" and triggered_det and not _has_vital_log_after(vital_log, det_minute):
            errors.append(_error(code, message, False, deduction or 15))
        elif code == "NO_REASSESSMENT_TIME_SET" and not any(d.get("reassessment_minutes") for d in triage_decisions if d.get("decision_type") == "initial"):
            errors.append(_error(code, message, False, deduction or 8))

    if triggered_det and LEVEL_RANK.get(standard_final or "", 4) <= 2 and not timely_notification:
        errors.append(_error("NO_DOCTOR_NOTIFICATION_AFTER_WORSENING", "候诊区危重化后未及时通知医生", True))

    rule_result = evaluate_minimum_triage_level(case_data, record)
    for code in rule_result.get("severe_error_codes", []):
        errors.append(_error(code, code, True))

    errors = _unique_errors(errors)
    critical_errors = [e for e in errors if e.get("critical_fail")]
    return {
        "serious_error_triggered": bool(critical_errors),
        "serious_error_codes": [e["code"] for e in errors],
        "serious_error_reasons": [e["message"] for e in errors],
        "final_result": "fail" if critical_errors else "pass",
        "override_reason": "; ".join(e["message"] for e in critical_errors),
        "errors": errors,
    }


def _error(code: str, message: str, critical_fail: bool, deduction: int = 0) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "critical_fail": critical_fail,
        "deduction": deduction,
    }


def _event_indicates_deterioration(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "").lower()
    return (
        event_type in {"deterioration", "critical_change", "symptom_worsening", "time_elapsed_without_reassessment"}
        or bool(event.get("severe_error_if_ignored"))
        or bool(event.get("standard_level_after_event"))
    )


def _is_red_area(area: str | None) -> bool:
    text = str(area or "")
    return any(token in text for token in ("红区", "抢救", "复苏", "急诊优先处置区"))


def _is_green_waiting_area(area: str | None) -> bool:
    text = str(area or "")
    return "绿区" in text and "绿色通道" not in text


def _timely_doctor_notification(record: dict[str, Any], deterioration_minute: int | None) -> bool:
    def timely(minute: Any) -> bool:
        if deterioration_minute is None:
            return True
        try:
            return int(minute or 0) >= deterioration_minute
        except (TypeError, ValueError):
            return False

    if any(timely(item.get("simulation_minute")) for item in record.get("notification_events") or []):
        return True
    for decision in record.get("triage_decisions") or []:
        if decision.get("notify_doctor") and timely(decision.get("simulation_minute")):
            return True
    for action in record.get("student_actions") or []:
        if action.get("action_type") == "notify_doctor" and timely(action.get("simulation_minute")):
            return True
    return False


def _has_vital_log_after(vital_log: list[dict[str, Any]], minute: int | None) -> bool:
    if minute is None:
        return bool(vital_log)
    for item in vital_log or []:
        try:
            if int(item.get("simulation_minute") or 0) >= minute:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _unique_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for item in errors:
        code = item.get("code")
        if code in seen:
            continue
        seen.add(code)
        unique.append(item)
    return unique
