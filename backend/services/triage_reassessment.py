"""V4 候诊复评管理

记录复评、判断是否按时、判断完整性、调用规则引擎复算等级。
"""

from datetime import datetime, timezone

VITAL_ALIASES = {
    "heart_rate": {"heart_rate", "heart_rate_bpm"},
    "respiratory_rate": {"respiratory_rate", "respiratory_rate_bpm"},
    "spo2": {"spo2", "spo2_percent"},
    "temperature": {"temperature", "temperature_c"},
    "pain_score": {"pain_score", "nrs"},
    "consciousness": {"consciousness", "mental_status", "gcs", "gcs_score"},
    "blood_glucose": {"blood_glucose", "blood_glucose_mmol_l"},
    "blood_pressure": {"blood_pressure", "systolic_bp_mmhg", "diastolic_bp_mmhg"},
}


def _latest_measured_items(record: dict, minute: int) -> list[str]:
    items: list[str] = []
    for entry in record.get("vital_measurement_log", []) or []:
        entry_minute = entry.get("simulation_minute")
        if entry_minute is not None and abs(int(entry_minute) - int(minute)) <= 5:
            for item in entry.get("measurement_ids", []) or []:
                if item and item not in items:
                    items.append(item)
    return items


def _matches_required(measured_item: str, required_item: str) -> bool:
    if measured_item == required_item:
        return True
    measured_aliases = VITAL_ALIASES.get(measured_item, {measured_item})
    required_aliases = VITAL_ALIASES.get(required_item, {required_item})
    return bool(measured_aliases & required_aliases)


def _calculate_completeness(required_items: list[str], measured_items: list[str]) -> float:
    if not measured_items:
        return 0.0
    if not required_items:
        return 1.0
    matched = 0
    for required in required_items:
        if any(_matches_required(measured, required) for measured in measured_items):
            matched += 1
    return matched / max(len(required_items), 1)


def _zone_for_level(level: str) -> str:
    from services.triage_rules.models import LEVEL_RANK

    rank = LEVEL_RANK.get(level, 4)
    if rank <= 2:
        return "红区"
    if rank == 3:
        return "黄区"
    return "绿区"


def _current_state_standard(case_data: dict | None, record: dict) -> tuple[str, str]:
    if not case_data:
        return "", ""
    state = record.get("timeline_state", {}) or {}
    current_state_id = state.get("current_patient_state_id")
    current_minute = int(state.get("current_simulated_minute") or 0)
    candidates = case_data.get("patient_states", []) or []

    selected = None
    for patient_state in candidates:
        if current_state_id and patient_state.get("state_id") == current_state_id:
            selected = patient_state
            break
    if selected is None:
        for patient_state in sorted(candidates, key=lambda item: item.get("time_minute", 0)):
            if int(patient_state.get("time_minute") or 0) <= current_minute:
                selected = patient_state

    if not selected:
        return "", ""
    return selected.get("standard_triage_level", ""), selected.get("standard_area", "")


def _apply_dynamic_state_standard(rule_result: dict, case_data: dict | None, record: dict, selected_level: str) -> dict:
    """For dynamic cases, the current patient state is the authoritative standard.

    Rule hits remain useful as teaching evidence, but they should not override a
    deliberately staged timeline where T15 can remain level III and T30 becomes
    level II.
    """
    if not rule_result or not case_data or not case_data.get("patient_states"):
        return rule_result

    state_level, state_area = _current_state_standard(case_data, record)
    if not state_level:
        return rule_result

    from services.triage_rules.models import LEVEL_RANK

    student_level = selected_level or record.get("final_level_selected") or "Ⅳ级"
    student_rank = LEVEL_RANK.get(student_level, 4)
    standard_rank = LEVEL_RANK.get(state_level, 4)
    level_diff = abs(student_rank - standard_rank)
    severe = (standard_rank <= 2 and student_rank >= 4) or level_diff >= 2

    adjusted = dict(rule_result)
    adjusted["state_standard_level"] = state_level
    adjusted["state_standard_area"] = state_area or _zone_for_level(state_level)
    adjusted["final_standard_level"] = state_level
    adjusted["recommended_zone"] = state_area or _zone_for_level(state_level)
    adjusted["under_triage"] = student_rank > standard_rank
    adjusted["over_triage"] = student_rank < standard_rank
    adjusted["severe_error_triggered"] = severe
    adjusted["severe_error_codes"] = (
        [f"SEVERE_UNDER_TRIAGE_{student_level}_TO_{state_level}"] if severe else []
    )
    adjusted["dynamic_state_standard_applied"] = True
    return adjusted


def create_reassessment(record: dict, payload: dict, case_data: dict = None) -> dict:
    """创建一次复评记录"""
    state = record.get("timeline_state", {})
    reassessments = state.get("reassessments", [])

    minute = state.get("current_simulated_minute", 0)
    measured_items = payload.get("measured_items") or _latest_measured_items(record, minute)
    required_items = state.get("reassessment_required_items") or []
    completeness = _calculate_completeness(required_items, measured_items)

    ra = {
        "id": len(reassessments) + 1,
        "minute": minute,
        "measured_items": measured_items,
        "required_items": required_items,
        "completeness": round(completeness, 2),
        "symptom_change_questioned": payload.get("symptom_change_questioned", False),
        "selected_level": payload.get("selected_level"),
        "selected_zone": payload.get("selected_zone"),
        "disposition": payload.get("disposition", []),
        "upgrade_needed": False,
        "upgraded_correctly": None,
        "rule_result_before": state.get("last_rule_result"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # P1-1: 更新复评完成标志和最后复评时间
    state["last_reassessment_minute"] = state.get("current_simulated_minute", 0)
    state["reassessment_completed"] = True
    # 检查是否在due前复评
    due = state.get("next_reassessment_due", 30)
    if state["last_reassessment_minute"] <= due + 5:
        state["reassessment_on_time"] = True
    else:
        state["reassessment_overdue"] = True

    # 检查是否升级
    initial_level = state.get("current_triage_level") or state.get("initial_level_selected")
    if initial_level and ra["selected_level"]:
        from services.triage_rules.models import LEVEL_RANK
        if LEVEL_RANK.get(ra["selected_level"], 4) < LEVEL_RANK.get(initial_level, 4):
            ra["upgraded_correctly"] = True
            state.setdefault("upgrades", []).append({
                "minute": state["current_simulated_minute"],
                "from_level": initial_level,
                "to_level": ra["selected_level"],
            })

    reassessments.append(ra)
    state["reassessments"] = reassessments

    # 调用规则引擎复算
    rule_result = None
    try:
        from services.triage_rules.engine import evaluate as rule_evaluate
        case = case_data
        if case:
            # 构建复评后的 record snapshot
            eval_record = {
                "disclosed_slots": record.get("disclosed_slots", []),
                "measured_vitals": list(set(
                    record.get("measured_vitals", []) + ra.get("measured_items", [])
                )),
                "final_level_selected": ra.get("selected_level") or record.get("final_level_selected"),
                "final_zone_selected": ra.get("selected_zone") or record.get("final_zone_selected"),
                "intent_events": record.get("intent_events", []),
            }
            result = rule_evaluate(case, eval_record)
            rule_result = result.to_dict()
            rule_result = _apply_dynamic_state_standard(
                rule_result,
                case,
                record,
                ra.get("selected_level") or record.get("final_level_selected"),
            )
            state["last_rule_result"] = rule_result
            ra["rule_result_after"] = rule_result
    except Exception:
        pass

    # 判断是否需要升级
    if rule_result and initial_level:
        from services.triage_rules.models import LEVEL_RANK
        expected_level = rule_result.get("final_standard_level") or rule_result.get("minimum_level_by_rules", "Ⅳ级")
        rule_min_rank = LEVEL_RANK.get(expected_level, 4)
        current_rank = LEVEL_RANK.get(ra.get("selected_level", initial_level), 4)
        ra["upgrade_needed"] = rule_min_rank < current_rank
        if ra["upgrade_needed"] and ra.get("upgraded_correctly") is None:
            ra["upgraded_correctly"] = ra["selected_level"] is not None and \
                LEVEL_RANK.get(ra["selected_level"], 4) <= rule_min_rank
        elif not ra["upgrade_needed"] and LEVEL_RANK.get(initial_level, 4) > rule_min_rank:
            ra["upgraded_correctly"] = ra["selected_level"] is not None and \
                LEVEL_RANK.get(ra["selected_level"], 4) <= rule_min_rank

    record["timeline_state"] = state
    return ra


def evaluate_reassessment(record: dict, ra_id: int) -> dict:
    """评估复评质量"""
    state = record.get("timeline_state", {})
    reassessments = state.get("reassessments", [])
    ra = next((r for r in reassessments if r.get("id") == ra_id), None)

    if not ra:
        return {"error": "复评记录不存在"}

    required_items = ra.get("required_items") or state.get("reassessment_required_items", [])
    measured = ra.get("measured_items", [])
    if not measured:
        measured = _latest_measured_items(record, ra.get("minute", state.get("current_simulated_minute", 0)))
        ra["measured_items"] = measured
    completeness = _calculate_completeness(required_items, measured)
    ra["completeness"] = round(completeness, 2)

    return {
        "reassessment_id": ra_id,
        "completeness": round(completeness, 2),
        "on_time": ra.get("minute", 0) <= state.get("next_reassessment_due", 30),
        "upgrade_needed": ra.get("upgrade_needed", False),
        "upgraded_correctly": ra.get("upgraded_correctly"),
        "rule_result": ra.get("rule_result_after"),
    }


def determine_upgrade_needed(rule_before: dict, rule_after: dict) -> bool:
    """判断是否需要升级"""
    if not rule_before or not rule_after:
        return False
    from services.triage_rules.models import LEVEL_RANK
    before = LEVEL_RANK.get(rule_before.get("minimum_level_by_rules", "Ⅳ级"), 4)
    after = LEVEL_RANK.get(rule_after.get("minimum_level_by_rules", "Ⅳ级"), 4)
    return after < before
