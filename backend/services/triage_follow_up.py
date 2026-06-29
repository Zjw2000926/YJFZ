"""Follow-up / waiting reassessment decision policy.

This module keeps dynamic behavior as a backend simulation rule while making
the student actively decide whether to observe, reassess, upgrade, or finish.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.case_types import is_dynamic_case
from services.triage_rules.models import LEVEL_RANK


FOLLOW_UP_OPTIONS = {
    "complete_no_reassessment",
    "observe_waiting",
    "reassess_5",
    "reassess_10",
    "reassess_15",
    "reassess_30",
    "remeasure_vitals_now",
    "upgrade_notify_doctor",
    "continue_history",
    "other",
}

REASSESSMENT_OPTIONS = {"observe_waiting", "reassess_5", "reassess_10", "reassess_15", "reassess_30"}


def build_follow_up_policy(case_data: dict[str, Any]) -> dict[str, Any]:
    """Build backend-only follow-up policy from explicit or legacy case fields."""
    explicit_required = case_data.get("requires_reassessment")
    dt = case_data.get("dynamic_timeline") or {}
    events = dt.get("events") or []
    dynamic = is_dynamic_case(case_data)
    has_deterioration = any(_event_indicates_deterioration(event) for event in events)

    initial_stage = dt.get("initial_stage") if isinstance(dt.get("initial_stage"), dict) else {}
    first_event_minute = min([_as_int(event.get("scheduled_minute"), 0) for event in events], default=None)
    recommended = (
        _as_int(case_data.get("recommended_reassessment_time"), None)
        or _as_int(initial_stage.get("reassessment_due_minutes"), None)
        or first_event_minute
        or 30
    )

    standard_initial = (
        case_data.get("standard_initial_triage_level")
        or (case_data.get("standard_answer") or {}).get("triage_level")
        or ""
    )
    standard_final = case_data.get("standard_final_triage_level") or standard_initial
    standard_rank = LEVEL_RANK.get(standard_final or standard_initial, 4)

    if explicit_required is None:
        requires = bool(dynamic and (events or _standard_answer_mentions_reassessment(case_data)))
    else:
        requires = bool(explicit_required)

    if case_data.get("case_dynamic_type"):
        dynamic_type = str(case_data.get("case_dynamic_type"))
    elif has_deterioration:
        dynamic_type = "progressive_deterioration"
    elif dynamic and events:
        dynamic_type = "potential_deterioration"
    elif standard_rank <= 2:
        dynamic_type = "critical"
    else:
        dynamic_type = "stable"

    reason = (
        case_data.get("reassessment_reason")
        or initial_stage.get("initial_risk")
        or (case_data.get("training_focus") or [])
        or (case_data.get("dynamic_feedback") or {}).get("key_red_flag")
        or []
    )
    if isinstance(reason, list):
        reason_text = "、".join(str(item) for item in reason if item)
    else:
        reason_text = str(reason or "")

    return {
        "case_dynamic_type": dynamic_type,
        "requires_reassessment": requires,
        "reassessment_reason": reason_text,
        "recommended_reassessment_time": int(recommended or 30),
        "reassessment_triggers": case_data.get("reassessment_triggers") or _event_trigger_texts(events),
        "consequence_if_no_reassessment": case_data.get("consequence_if_no_reassessment")
        or dt.get("failure_consequence")
        or "可能错过候诊期间病情变化。",
        "reassessment_required_after_node": bool(case_data.get("reassessment_required_after_node") or has_deterioration),
        "has_backend_state_change": bool(dynamic and events),
        "standard_final_rank": standard_rank,
    }


def get_follow_up_options() -> list[dict[str, Any]]:
    return [
        {"id": "complete_no_reassessment", "label": "完成分诊，无需复评"},
        {"id": "observe_waiting", "label": "安排候诊观察"},
        {"id": "reassess_5", "label": "安排 5 分钟后复评", "minutes": 5},
        {"id": "reassess_10", "label": "安排 10 分钟后复评", "minutes": 10},
        {"id": "reassess_15", "label": "安排 15 分钟后复评", "minutes": 15},
        {"id": "reassess_30", "label": "安排 30 分钟后复评", "minutes": 30},
        {"id": "remeasure_vitals_now", "label": "立即再次测量生命体征"},
        {"id": "upgrade_notify_doctor", "label": "立即升级处理/通知医生"},
        {"id": "continue_history", "label": "继续补充关键病史"},
        {"id": "other", "label": "其他处理措施"},
    ]


def record_follow_up_decision(record: dict[str, Any], case_data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    policy = build_follow_up_policy(case_data)
    option = str(payload.get("selected_option") or "")
    if option not in FOLLOW_UP_OPTIONS:
        raise ValueError("未知的候诊与复评决策")

    minute = _current_minute(record)
    selected_time = _selected_time(option, payload)
    evaluation = evaluate_follow_up_choice(policy, option, selected_time, record)
    decision = {
        "decision_id": f"followup-{len(record.get('follow_up_decisions') or []) + 1}",
        "decision_type": "follow_up_management",
        "selected_option": option,
        "selected_time": selected_time,
        "case_stage": payload.get("case_stage") or _current_stage(record),
        "simulation_minute": minute,
        "whether_correct": evaluation["whether_correct"],
        "score_change": evaluation["score_change"],
        "feedback_message": evaluation["feedback_message"],
        "issue_code": evaluation.get("issue_code", ""),
        "policy_snapshot": {
            "requires_reassessment": policy["requires_reassessment"],
            "recommended_reassessment_time": policy["recommended_reassessment_time"],
            "case_dynamic_type": policy["case_dynamic_type"],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    record.setdefault("follow_up_decisions", []).append(decision)
    record.setdefault("student_actions", []).append({
        "action_id": f"action-{len(record.get('student_actions') or []) + 1}",
        "action_type": "follow_up_decision",
        "simulation_minute": minute,
        "detail": {
            "selected_option": option,
            "selected_time": selected_time,
            "case_stage": decision["case_stage"],
        },
        "is_key_action": True,
        "is_required": True,
        "is_correct": evaluation["whether_correct"],
        "is_late": evaluation.get("is_late", False),
        "score_delta": evaluation["score_change"],
        "feedback": evaluation["feedback_message"],
        "timestamp": decision["created_at"],
    })

    state = record.setdefault("timeline_state", {})
    state["awaiting_follow_up_decision"] = False
    if option in REASSESSMENT_OPTIONS:
        state["next_reassessment_due"] = selected_time or policy["recommended_reassessment_time"]
    if option == "upgrade_notify_doctor":
        record.setdefault("notification_events", []).append({
            "simulation_minute": minute,
            "reason": payload.get("reason") or "学员选择立即升级处理/通知医生",
            "source": "follow_up_decision",
            "timestamp": decision["created_at"],
        })

    return {"decision": decision, "policy": policy, "evaluation": evaluation}


def evaluate_follow_up_choice(
    policy: dict[str, Any],
    option: str,
    selected_time: int | None,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requires = bool(policy.get("requires_reassessment"))
    recommended = int(policy.get("recommended_reassessment_time") or 30)
    dynamic_type = str(policy.get("case_dynamic_type") or "stable")
    is_high_risk = dynamic_type in {"potential_deterioration", "progressive_deterioration", "critical"}
    option_is_reassessment = option in REASSESSMENT_OPTIONS
    option_is_upgrade = option == "upgrade_notify_doctor"

    if requires:
        if option_is_reassessment:
            late = bool(selected_time and selected_time > recommended + 5)
            if late:
                return {
                    "whether_correct": False,
                    "score_change": -3,
                    "is_late": True,
                    "issue_code": "FOLLOW_UP_TOO_LATE",
                    "feedback_message": "已安排复评/观察，但时间偏晚，可能降低候诊风险识别的及时性。",
                }
            return {
                "whether_correct": True,
                "score_change": 6,
                "feedback_message": "已根据患者候诊风险安排观察或短时间复评，符合预检分诊中的动态风险管理思路。",
            }
        if option == "complete_no_reassessment":
            return {
                "whether_correct": False,
                "score_change": -12 if is_high_risk else -6,
                "issue_code": "MISSED_REQUIRED_FOLLOW_UP",
                "critical_fail": is_high_risk,
                "feedback_message": "该患者存在继续观察或复评指征，直接结束分诊有漏评候诊风险。",
            }
        if option_is_upgrade:
            correct = is_high_risk or int(policy.get("standard_final_rank") or 4) <= 2
            return {
                "whether_correct": correct,
                "score_change": 4 if correct else -2,
                "issue_code": "" if correct else "POSSIBLE_OVER_TRIAGE",
                "feedback_message": "已选择升级处理/通知医生。" if correct else "目前证据不足以支持立即升级处理，应结合红旗信号和生命体征判断。",
            }
        return {
            "whether_correct": False,
            "score_change": -2,
            "issue_code": "FOLLOW_UP_DECISION_INCOMPLETE",
            "feedback_message": "该选择可作为补充措施，但仍需明确候诊观察或复评安排。",
        }

    if option == "complete_no_reassessment":
        return {
            "whether_correct": True,
            "score_change": 4,
            "feedback_message": "当前病例缺乏明确候诊复评指征，完成分诊并进入相应区域较为合理。",
        }
    if option_is_reassessment:
        return {
            "whether_correct": False,
            "score_change": -2,
            "issue_code": "OVER_REASSESSMENT",
            "feedback_message": "当前病情相对稳定，缺乏明确复评指征，过度复评会降低分诊效率。",
        }
    if option_is_upgrade:
        return {
            "whether_correct": False,
            "score_change": -4,
            "issue_code": "OVER_TRIAGE",
            "feedback_message": "目前证据不足以支持立即升级处理，存在过度分诊或资源使用不合理。",
        }
    return {
        "whether_correct": False,
        "score_change": -1,
        "issue_code": "NON_FINAL_FOLLOW_UP_DECISION",
        "feedback_message": "该选择可作为补充，但应形成明确的去向或候诊管理策略。",
    }


def should_advance_after_decision(result: dict[str, Any]) -> bool:
    decision = result.get("decision") or {}
    policy = result.get("policy") or {}
    return (
        bool(policy.get("requires_reassessment"))
        and bool(policy.get("has_backend_state_change"))
        and decision.get("selected_option") in REASSESSMENT_OPTIONS
        and decision.get("whether_correct") is True
    )


def score_follow_up_decisions(record: dict[str, Any], case_data: dict[str, Any], max_score: int = 8) -> dict[str, Any]:
    policy = build_follow_up_policy(case_data)
    decisions = record.get("follow_up_decisions") or []
    if not decisions:
        legacy_reassessed = bool((record.get("timeline_state") or {}).get("reassessment_completed")) or any(
            action.get("action_type") in {"reassess", "advance_time"} for action in record.get("student_actions") or []
        )
        legacy_reassessment_time = any(
            decision.get("reassessment_minutes")
            for decision in record.get("triage_decisions") or []
            if decision.get("decision_type") == "initial"
        )
        if policy["requires_reassessment"] and (legacy_reassessed or legacy_reassessment_time):
            return {
                "score": max_score,
                "max": max_score,
                "issue_codes": [],
                "serious_errors": [],
                "summary": "已通过复评/候诊相关操作留下证据；建议后续使用候诊与复评决策栏记录。",
                "policy": policy,
                "decisions": [],
            }
        if policy["requires_reassessment"]:
            critical = policy["case_dynamic_type"] in {"potential_deterioration", "progressive_deterioration", "critical"}
            return {
                "score": 0,
                "max": max_score,
                "issue_codes": ["MISSED_REQUIRED_FOLLOW_UP"],
                "serious_errors": [_follow_up_error("MISSED_REQUIRED_FOLLOW_UP", "未选择必要的候诊观察或复评", critical)],
                "summary": "未记录候诊与复评决策。",
            }
        return {
            "score": max_score,
            "max": max_score,
            "issue_codes": [],
            "serious_errors": [],
            "summary": "稳定病例未强制要求候诊复评。",
        }

    best = max(decisions, key=lambda item: float(item.get("score_change") or 0))
    issue_codes = [item.get("issue_code") for item in decisions if item.get("issue_code")]
    if best.get("whether_correct"):
        score = max_score
    else:
        score = max(0, min(max_score, max_score + int(best.get("score_change") or 0)))
    errors = []
    for decision in decisions:
        if decision.get("issue_code") == "MISSED_REQUIRED_FOLLOW_UP":
            critical = policy["case_dynamic_type"] in {"potential_deterioration", "progressive_deterioration", "critical"}
            errors.append(_follow_up_error("MISSED_REQUIRED_FOLLOW_UP", "需要复评/观察的患者未安排候诊复评", critical))
        elif decision.get("issue_code") == "OVER_REASSESSMENT":
            errors.append(_follow_up_error("OVER_REASSESSMENT", "稳定病例选择了不必要复评/观察", False, 2))
        elif decision.get("issue_code") == "OVER_TRIAGE":
            errors.append(_follow_up_error("OVER_TRIAGE", "缺乏依据的立即升级处理", False, 4))

    return {
        "score": score,
        "max": max_score,
        "issue_codes": [code for code in issue_codes if code],
        "serious_errors": errors,
        "summary": best.get("feedback_message", ""),
        "policy": policy,
        "decisions": decisions,
    }


def _follow_up_error(code: str, message: str, critical_fail: bool, deduction: int = 0) -> dict[str, Any]:
    return {"code": code, "message": message, "critical_fail": critical_fail, "deduction": deduction}


def _selected_time(option: str, payload: dict[str, Any]) -> int | None:
    if payload.get("selected_time") is not None:
        return _as_int(payload.get("selected_time"), None)
    if option.startswith("reassess_"):
        return _as_int(option.replace("reassess_", ""), None)
    return None


def _current_minute(record: dict[str, Any]) -> int:
    return _as_int((record.get("timeline_state") or {}).get("current_simulated_minute"), 0) or 0


def _current_stage(record: dict[str, Any]) -> str:
    return str((record.get("timeline_state") or {}).get("current_stage") or "INITIAL_TRIAGE")


def _as_int(value: Any, fallback: int | None = 0) -> int | None:
    try:
        if value is None or value == "":
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _standard_answer_mentions_reassessment(case_data: dict[str, Any]) -> bool:
    text = " ".join(str(item) for item in ((case_data.get("standard_answer") or {}).get("disposition") or []))
    text += " " + str((case_data.get("standard_answer") or {}).get("reassessment_plan") or "")
    return any(token in text for token in ("复评", "观察", "候诊"))


def _event_trigger_texts(events: list[dict[str, Any]]) -> list[str]:
    triggers = []
    for event in events or []:
        text = event.get("trigger_condition") or event.get("event_description") or event.get("patient_expression")
        if text:
            triggers.append(str(text))
    return triggers


def _event_indicates_deterioration(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "").lower()
    return (
        event_type in {"deterioration", "critical_change", "symptom_worsening", "time_elapsed_without_reassessment"}
        or bool(event.get("severe_error_if_ignored"))
        or bool(event.get("standard_level_after_event"))
    )
