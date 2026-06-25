"""V4 候诊复评管理

记录复评、判断是否按时、判断完整性、调用规则引擎复算等级。
"""

from datetime import datetime, timezone

def create_reassessment(record: dict, payload: dict, case_data: dict = None) -> dict:
    """创建一次复评记录"""
    state = record.get("timeline_state", {})
    reassessments = state.get("reassessments", [])

    ra = {
        "id": len(reassessments) + 1,
        "minute": state.get("current_simulated_minute", 0),
        "measured_items": payload.get("measured_items", []),
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
    initial_level = state.get("initial_level_selected")
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
            state["last_rule_result"] = rule_result
            ra["rule_result_after"] = rule_result
    except Exception:
        pass

    # 判断是否需要升级
    if rule_result and initial_level:
        from services.triage_rules.models import LEVEL_RANK
        rule_min_rank = LEVEL_RANK.get(rule_result.get("minimum_level_by_rules", "Ⅳ级"), 4)
        current_rank = LEVEL_RANK.get(ra.get("selected_level", initial_level), 4)
        ra["upgrade_needed"] = rule_min_rank < current_rank
        if ra["upgrade_needed"] and ra.get("upgraded_correctly") is None:
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

    required_items = state.get("reassessment_required_items", [])
    measured = ra.get("measured_items", [])
    completeness = len([i for i in required_items if i in measured]) / max(len(required_items), 1)

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
