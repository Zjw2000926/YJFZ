"""Scoring facade for static and dynamic triage cases."""

from typing import Any

from services.case_types import is_dynamic_case
from services.triage_scoring_real_rubric import score_triage_real_rubric
from services.triage_scoring_v1 import score_triage_record
from services.triage_scoring_v3 import score_triage_v3
from services.triage_scoring_v4 import score_triage_v4
from services.score_explanation import enrich_score_result
from services.triage_follow_up import score_follow_up_decisions


def score_case(record: dict[str, Any], case_data: dict[str, Any]) -> dict[str, Any]:
    if is_dynamic_case(case_data):
        result = score_dynamic_case(record, case_data)
    else:
        result = score_static_case(record, case_data)
    return enrich_score_result(record, case_data, result)


def score_static_case(record: dict[str, Any], case_data: dict[str, Any]) -> dict[str, Any]:
    if case_data.get("scoring_rubric"):
        result = score_triage_real_rubric(record, case_data)
    elif case_data.get("dialogue_state_machine"):
        result = score_triage_v3(record, case_data)
    else:
        result = score_triage_record(record, case_data)
    _apply_follow_up_adjustment(result, record, case_data)
    if not result.get("timeline_report"):
        from services.report_generator import generate_training_report
        from services.triage_rule_engine import detect_serious_errors
        serious_result = {
            "serious_error_triggered": result.get("severe_error_triggered", False),
            "serious_error_codes": result.get("severe_errors", []),
            "serious_error_reasons": result.get("severe_errors", []),
            "final_result": "fail" if result.get("severe_error_triggered") else "pass",
            "override_reason": "",
            "errors": result.get("severe_errors", []),
        }
        if not serious_result.get("serious_error_triggered"):
            serious_result = detect_serious_errors(case_data, record)
        result["timeline_report"] = generate_training_report(record, case_data, result.get("detail_scores", {}), serious_result)
    return result


def score_dynamic_case(record: dict[str, Any], case_data: dict[str, Any]) -> dict[str, Any]:
    return score_triage_v4(record, case_data)


def _apply_follow_up_adjustment(result: dict[str, Any], record: dict[str, Any], case_data: dict[str, Any]) -> None:
    follow_up = score_follow_up_decisions(record, case_data, max_score=8)
    issues = follow_up.get("issue_codes") or []
    if not issues:
        return
    deduction = 0
    if "MISSED_REQUIRED_FOLLOW_UP" in issues:
        deduction += 8
    if "OVER_REASSESSMENT" in issues:
        deduction += 2
    if "OVER_TRIAGE" in issues:
        deduction += 4
    if deduction:
        base = float(result.get("total_score") or result.get("effective_score") or 0)
        result["total_score"] = max(0, round(base - deduction, 2))
        result["effective_score"] = result["total_score"]
    critical = [err for err in follow_up.get("serious_errors") or [] if err.get("critical_fail")]
    if critical:
        result["severe_error_triggered"] = True
        result["severe_errors"] = list({*(result.get("severe_errors") or []), *[err.get("code") for err in critical]})
        result["total_score"] = min(float(result.get("total_score") or 0), 59)
        result["effective_score"] = result["total_score"]
        result["pass_status"] = "fail"
    result.setdefault("feedback", {})
    if isinstance(result["feedback"], dict):
        result["feedback"]["follow_up_decision_summary"] = follow_up.get("summary", "")
