"""Scoring facade for static and dynamic triage cases."""

from typing import Any

from services.case_types import is_dynamic_case
from services.triage_scoring_real_rubric import score_triage_real_rubric
from services.triage_scoring_v1 import score_triage_record
from services.triage_scoring_v3 import score_triage_v3
from services.triage_scoring_v4 import score_triage_v4


def score_case(record: dict[str, Any], case_data: dict[str, Any]) -> dict[str, Any]:
    if is_dynamic_case(case_data):
        return score_dynamic_case(record, case_data)
    return score_static_case(record, case_data)


def score_static_case(record: dict[str, Any], case_data: dict[str, Any]) -> dict[str, Any]:
    if case_data.get("scoring_rubric"):
        result = score_triage_real_rubric(record, case_data)
    elif case_data.get("dialogue_state_machine"):
        result = score_triage_v3(record, case_data)
    else:
        result = score_triage_record(record, case_data)
    if not result.get("timeline_report"):
        from services.report_generator import generate_training_report
        serious_result = {
            "serious_error_triggered": result.get("severe_error_triggered", False),
            "serious_error_codes": result.get("severe_errors", []),
            "serious_error_reasons": result.get("severe_errors", []),
            "final_result": "fail" if result.get("severe_error_triggered") else "pass",
            "override_reason": "",
            "errors": result.get("severe_errors", []),
        }
        result["timeline_report"] = generate_training_report(record, case_data, result.get("detail_scores", {}), serious_result)
    return result


def score_dynamic_case(record: dict[str, Any], case_data: dict[str, Any]) -> dict[str, Any]:
    return score_triage_v4(record, case_data)
