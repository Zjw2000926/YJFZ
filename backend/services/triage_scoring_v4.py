"""V4 动态病例评分引擎

评分维度（100分）：
- 初始第一眼评估 (8)
- 初始病史采集 (12)
- 初始生命体征评估 (12)
- 初始高危信号识别 (15)
- 初始分诊等级 (15)
- 初始处置安排 (8)
- 复评时间设置 (8)
- 复评内容完成 (10)
- 病情变化识别与升级 (8)
- 沟通记录 (4)

严重错误(一票否决):
- 未设置Ⅲ级患者复评时间
- 恶化后未复评
- 复评后恶化仍未升级
- 危重化未通知医生
- 未记录病情变化
"""

from services.triage_rules.models import LEVEL_RANK
from services.triage_rule_engine import detect_serious_errors, evaluate_minimum_triage_level
from services.report_generator import (
    event_indicates_deterioration,
    generate_training_report,
    student_recognized_deterioration,
    _clean_training_suggestions,
)


def score_triage_v4(record: dict, case_data: dict) -> dict:
    """V4 动态病例评分（含 MVP 动态评分 rubric）"""
    state = record.get("timeline_state", {})
    disclosed = record.get("disclosed_slots", [])
    measured = record.get("measured_vitals", [])
    final_level = record.get("final_level_selected", "Ⅳ级")
    dt = case_data.get("dynamic_timeline", {})
    triage_decisions = record.get("triage_decisions", [])
    vital_log = record.get("vital_measurement_log", [])
    student_actions = record.get("student_actions", [])

    # 使用 dynamic_scoring_rubric 维度或默认维度
    dsr = case_data.get("dynamic_scoring_rubric", {})
    dims = dsr.get("dimensions", []) if dsr else []

    # 初始评分
    vital_count = len(measured)
    slot_count = len(disclosed)
    intent_count = len({e.get("intent") for e in record.get("intent_events", []) or [] if e.get("intent")})
    question_count = len([m for m in record.get("messages", []) or [] if m.get("role") == "student"])
    observed_count = len(record.get("observed_items", []))
    first_look = min(8, int(8 * (observed_count + slot_count / 2) / 8)) if observed_count > 0 else 3
    history_basis = max(len(case_data.get("dialogue_state_machine", {}).get("slots", [])), 1)
    history_evidence = slot_count + intent_count
    history = min(12, int(12 * history_evidence / history_basis))
    if question_count:
        history = max(history, min(10, question_count * 2))
    vitals = min(12, int(12 * len(vital_log) / 3)) if vital_log else min(12, int(12 * vital_count / max(len(case_data.get("required_measurements", [])), 1)))

    # 规则引擎
    rd = evaluate_minimum_triage_level(case_data, record)

    rule_hits = rd.get("rule_hits", []) if isinstance(rd, dict) else []
    cs = 15 if len(rule_hits) > 0 else 5
    init_decisions = [d for d in triage_decisions if d.get("decision_type") == "initial"]
    level_ok = True
    if init_decisions:
        init_lv = init_decisions[0].get("level", "")
        standard_init = case_data.get("standard_initial_triage_level") or case_data.get("standard_answer", {}).get("triage_level", "")
        # 学生等级越高(rank越小)=越紧急，不能低于标准(rank更大)。标准III(3)，学生II(2)或I(1)都可以，但IV(4)不行
        level_ok = LEVEL_RANK.get(init_lv, 4) <= LEVEL_RANK.get(standard_init, 4) if standard_init else True
    lv = 15 if level_ok else 5

    disp = min(8, 5 + min(3, len(record.get("final_disposition", []))))

    # 复评
    reassessments = state.get("reassessments", [])
    ra_decisions = [d for d in triage_decisions if d.get("decision_type") == "reassessment"]
    ra_count = max(len(reassessments), len(ra_decisions))
    recheck_time = 8 if triage_decisions and any(d.get("reassessment_minutes") for d in triage_decisions if d.get("decision_type") == "initial") else 0
    if reassessments:
        best_completeness = max(float(r.get("completeness", 0) or 0) for r in reassessments)
        ra_content = min(10, int(round(10 * best_completeness)))
        if ra_content == 0 and ra_count > 0:
            ra_content = 3
    else:
        ra_content = 0

    # 升级识别
    events = dt.get("events", [])
    deterioration_events = [e for e in events if event_indicates_deterioration(e)]
    upgrade_detected = 0
    if deterioration_events:
        for e in deterioration_events:
            for d in ra_decisions:
                # LEVEL_RANK: I=1, II=2, III=3, IV=4 → 升级意味着更小的值
                if d.get("level") and LEVEL_RANK.get(d.get("level", "Ⅳ级"), 4) <= LEVEL_RANK.get(e.get("standard_level_after_event", "Ⅱ级"), 2):
                    upgrade_detected += 1
                    break
    upgrade_score = min(8, int(8 * upgrade_detected / max(len(deterioration_events), 1))) if deterioration_events else 8

    comm = min(4, 2 + int(2 * (1 if record.get("notification_events") else 0)))

    # 使用 dynamic_scoring_rubric 维度名称或默认
    detail_dim_names = [d.get("name", d.get("key", "")) for d in dims] if dims else [
        "初始第一眼评估", "初始病史采集", "初始生命体征评估", "初始高危信号识别",
        "初始分诊等级", "初始处置安排", "复评时间设置", "复评内容完成",
        "病情变化识别与升级", "沟通记录"
    ]
    detail_maxes = [d.get("max_score", 8) for d in dims] if dims else [8, 12, 12, 15, 15, 8, 8, 10, 8, 4]
    scores = [first_look, history, vitals, cs, lv, disp, recheck_time, ra_content, upgrade_score, comm]

    # 对齐长度
    while len(scores) < len(detail_dim_names):
        scores.append(4)
    while len(scores) > len(detail_dim_names):
        detail_dim_names.append(f"维度{len(detail_dim_names)+1}")
        detail_maxes.append(4)

    detail = {}
    for i, name in enumerate(detail_dim_names):
        mx = detail_maxes[i] if i < len(detail_maxes) else 4
        sc = min(scores[i] if i < len(scores) else 0, mx)
        detail[name] = {"score": sc, "max": mx}
    total = sum(d["score"] for d in detail.values())
    total = max(0, min(100, total))

    serious_result = detect_serious_errors(case_data, record)
    severe = serious_result.get("errors", [])
    has_critical = any(s.get("critical_fail") for s in severe)
    total_deduction = sum(s.get("deduction", 0) for s in severe if not s.get("critical_fail"))
    effective = max(0, total - total_deduction)
    if has_critical:
        effective = min(effective, 59)

    ps = "fail" if has_critical else ("excellent" if effective >= 90 else "good" if effective >= 80 else "pass" if effective >= 60 else "fail")

    timeline_report = generate_training_report(record, case_data, detail, serious_result)

    return {
        "total_score": effective, "pass_status": ps,
        "severe_error_triggered": has_critical,
        "severe_errors": severe,
        "serious_error_triggered": serious_result.get("serious_error_triggered", False),
        "serious_error_codes": serious_result.get("serious_error_codes", []),
        "serious_error_reasons": serious_result.get("serious_error_reasons", []),
        "final_result": serious_result.get("final_result", ps),
        "override_reason": serious_result.get("override_reason", ""),
        "detail_scores": detail,
        "effective_score": effective,
        "rule_result": rd,
        "standard_answer": {
            "triage_level": case_data.get("standard_answer", {}).get("triage_level"),
            "standard_initial_triage_level": case_data.get("standard_initial_triage_level"),
            "standard_final_triage_level": case_data.get("standard_final_triage_level"),
        },
        "timeline_report": timeline_report,
        "feedback": {
            "correct_points": case_data.get("dynamic_feedback", {}).get("correct_points", []),
            "risk_if_missed": case_data.get("dynamic_feedback", {}).get("risk_if_missed", []),
            "key_red_flag": case_data.get("dynamic_feedback", {}).get("key_red_flag", []),
            "reason_for_triage_level": case_data.get("dynamic_feedback", {}).get("reason_for_triage_level", ""),
            "recommended_remediation": _clean_training_suggestions(case_data.get("dynamic_feedback", {}).get("recommended_remediation", [])),
            "strengths": [f"{k}:{v['score']}/{v['max']}" for k, v in detail.items() if v['score'] >= v['max'] * 0.7],
            "weaknesses": [f"{k}:{v['score']}/{v['max']}" for k, v in detail.items() if v['score'] < v['max'] * 0.5],
            "suggestions": "严重错误触发，一票否决。" if has_critical else "请关注候诊复评和病情变化识别。",
        }
    }


def _build_timeline_report(record: dict, case_data: dict, reassessments: list) -> dict:
    """生成完整动态时间线报告（MVP 验收报告）"""
    state = record.get("timeline_state", {})
    triage_decisions = record.get("triage_decisions", [])
    student_actions = record.get("student_actions", [])
    vital_log = record.get("vital_measurement_log", [])
    notification_events = record.get("notification_events", [])
    notes = record.get("notes", [])

    # 标准答案
    standard_init_level = case_data.get("standard_initial_triage_level") or case_data.get("standard_answer", {}).get("triage_level")
    standard_init_area = case_data.get("standard_initial_area") or case_data.get("standard_answer", {}).get("triage_zone")
    standard_final_level = case_data.get("standard_final_triage_level") or standard_init_level
    standard_final_area = case_data.get("standard_final_area") or standard_init_area

    # 学员决策
    init_decision = next((d for d in triage_decisions if d.get("decision_type") == "initial"), None)
    ra_decisions = [d for d in triage_decisions if d.get("decision_type") == "reassessment"]
    last_ra = ra_decisions[-1] if ra_decisions else None

    student_init_level = init_decision.get("level") if init_decision else record.get("final_level_selected")
    student_init_area = init_decision.get("area") if init_decision else record.get("final_zone_selected")
    student_final_level = last_ra.get("level") if last_ra else student_init_level
    student_final_area = last_ra.get("area") if last_ra else student_init_area

    # 时间线节点
    timeline_nodes = []
    # T0
    timeline_nodes.append({
        "minute": 0, "label": "T0 初诊",
        "event": case_data.get("initial_exposure", {}).get("chief_complaint", "")[:50],
        "student_action": f"初始分诊 {student_init_level} / {student_init_area}",
        "had_reassessment": False,
    })
    # 事件节点
    for ev in state.get("timeline_events", []):
        if ev.get("triggered"):
            timeline_nodes.append({
                "minute": ev.get("scheduled_minute", 0),
                "label": f"T{ev.get('scheduled_minute', 0)} {ev.get('event_type', '')}",
                "event": ev.get("event_description", ev.get("patient_expression", ""))[:60],
                "student_action": _describe_student_actions_at_minute(student_actions, ev.get("scheduled_minute", 0)),
                "had_reassessment": any(abs(a.get("simulation_minute", 0) - ev.get("scheduled_minute", 0)) <= 5
                                      for a in student_actions if a.get("action_type") == "reassess"),
                "had_upgrade": any(abs(a.get("simulation_minute", 0) - ev.get("scheduled_minute", 0)) <= 5
                                  for a in student_actions if a.get("action_type") == "upgrade_triage"),
            })

    # 复评判定
    # P1-1: 优先使用 state.reassessment_on_time 和 reassessment_overdue
    reassessment_on_time = state.get("reassessment_on_time", False) or (state.get("reassessment_completed", False) and not state.get("reassessment_overdue", False))
    deterioration_recognized = student_recognized_deterioration(record)
    triage_upgraded = student_final_level != student_init_level and _level_is_upgrade(student_init_level, student_final_level)
    doctor_notified = len(notification_events) > 0

    return {
        "standard_initial_level": standard_init_level or "",
        "standard_initial_area": standard_init_area or "",
        "standard_final_level": standard_final_level or "",
        "standard_final_area": standard_final_area or "",
        "student_initial_level": student_init_level or "",
        "student_initial_area": student_init_area or "",
        "student_final_level": student_final_level or "",
        "student_final_area": student_final_area or "",
        "timeline_nodes": timeline_nodes,
        "triage_decisions": triage_decisions,
        "student_actions": [{"action_type": a.get("action_type", ""), "minute": a.get("simulation_minute", 0),
                             "detail": a.get("detail", {})} for a in (student_actions or [])[-20:]],
        "vital_measurement_log": vital_log,
        "reassessment_on_time": reassessment_on_time,
        "deterioration_recognized": deterioration_recognized,
        "triage_upgraded": triage_upgraded,
        "doctor_notified": doctor_notified,
        "notification_events": notification_events,
        "notes": notes,
    }


def _level_is_upgrade(from_level: str, to_level: str) -> bool:
    """判断分诊等级是否为升级（Ⅰ级最高 > Ⅱ级 > Ⅲ级 > Ⅳ级最低，rank越小越紧急）"""
    rank = {"Ⅰ级": 1, "Ⅱ级": 2, "Ⅲ级": 3, "Ⅳ级": 4}
    return rank.get(from_level, 5) > rank.get(to_level, 5)  # from III(3) > to II(2) = True


def _describe_student_actions_at_minute(actions: list, minute: int) -> str:
    """描述学员在某时间点附近的操作"""
    nearby = [a for a in (actions or []) if abs(a.get("simulation_minute", 0) - minute) <= 5]
    if not nearby:
        return "无操作记录"
    types = [a.get("action_type", "") for a in nearby]
    type_labels = {
        "measure_vitals": "测量生命体征", "reassess": "执行复评",
        "upgrade_triage": "升级分诊", "notify_doctor": "通知医生",
        "advance_time": "推进时间", "initial_triage": "初始分诊",
    }
    labels = [type_labels.get(t, t) for t in types if t]
    return "、".join(labels[:3]) if labels else "无操作记录"
