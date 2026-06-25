"""V2 预检分诊评分引擎

评分依据：意图事件 + 行为轨迹（不再只依赖文本总结）
- intent_events: 判断问了什么
- triage_actions: 判断测量了什么
- final_level_selected: 判断等级
- critical_signal_ids: 判断高危识别

V2 评分维度（8项，100分）：
第一眼评估(8) + 主诉采集(10) + 聚焦病史(15) + 生命体征(15)
+ 高危信号(20) + 分诊等级(20) + 处置(7) + 沟通(5)
含 5 项扣分规则
"""

import json, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUBRIC_PATH = os.path.join(BASE_DIR, "triage_data", "rubrics", "triage_v2.json")

_rubric_cache = None

def _load_rubric():
    global _rubric_cache
    if _rubric_cache is None:
        with open(RUBRIC_PATH, "r", encoding="utf-8") as f:
            _rubric_cache = json.load(f)
    return _rubric_cache


def score_triage_v2(record: dict, case_data: dict) -> dict:
    """V2 评分主函数"""
    rubric = _load_rubric()

    disclosed = record.get("disclosed_slots", [])
    measured = record.get("measured_vitals", [])
    final_level = record.get("final_level_selected")
    final_zone = record.get("final_zone_selected")
    intent_events = record.get("intent_events", [])

    standard = case_data.get("standard_answer", {})
    state_machine = case_data.get("dialogue_state_machine", {})
    all_slots = state_machine.get("slots", [])
    critical_signals = case_data.get("critical_signals", [])
    severe_errors = case_data.get("severe_errors", [])

    required_slots = [s for s in all_slots if s.get("is_required")]
    required_count = len(required_slots)
    disclosed_count = len([s for s in required_slots if s["slot_id"] in disclosed])

    # 1. 第一眼评估 (8分)
    first_look_score = min(8, int(8 * disclosed_count / max(required_count, 1)))

    # 2. 主诉采集 (10分)
    chief_ids = ["onset_time", "chief_complaint"]
    chief_hits = len([s for s in chief_ids if s in disclosed])
    chief_score = min(10, int(10 * chief_hits / 2))

    # 3. 聚焦病史采集 (15分)
    history_slots = ["pain_location", "pain_nature", "severity", "duration",
                     "aggravating_relieving", "accompanying", "past_history",
                     "medication", "allergy"]
    history_hits = len([s for s in history_slots if s in disclosed])
    history_score = min(15, int(15 * history_hits / max(len(history_slots), 1)))

    # 4. 生命体征评估 (15分)
    all_ms = case_data.get("required_measurements", [])
    vital_score = min(15, int(15 * len(measured) / max(len(all_ms), 1)))

    # 5. 高危信号识别 (20分)
    cs_score = 0
    if critical_signals:
        for cs in critical_signals:
            evidence_ids = cs.get("evidence", [])
            cs_slots = []
            for slot in all_slots:
                if slot.get("slot_id") in disclosed:
                    for ev in evidence_ids:
                        if any(kw in str(slot.get("answer_facts", [])) for kw in [ev[:3]] if ev):
                            cs_slots.append(slot["slot_id"])
            if cs_slots:
                cs_score = 20
                break
        if cs_score == 0 and disclosed_count >= required_count * 0.5:
            cs_score = 10

    # 6. 分诊等级 (20分)
    std_level = standard.get("triage_level", "")
    if final_level == std_level:
        level_score = 20
    else:
        diff = _level_diff(final_level, std_level)
        level_score = max(0, 20 - diff * 10)

    # 7. 处置安排 (7分)
    std_zone = standard.get("triage_zone", "")
    zone_ok = final_zone and (final_zone in std_zone or std_zone in final_zone)
    zone_score = 3 if zone_ok else 0
    disp = record.get("final_disposition", [])
    disp_score = min(4, len(disp))
    dispo_score = zone_score + disp_score

    # 8. 沟通记录 (5分)
    comm_score = min(5, int(5 * disclosed_count / max(required_count, 1)))

    detail = {
        "第一眼评估": {"score": first_look_score, "max": 8},
        "主诉采集": {"score": chief_score, "max": 10},
        "聚焦病史采集": {"score": history_score, "max": 15},
        "生命体征评估": {"score": vital_score, "max": 15},
        "高危信号识别": {"score": cs_score, "max": 20},
        "分诊等级判断": {"score": level_score, "max": 20},
        "处置安排": {"score": dispo_score, "max": 7},
        "沟通记录": {"score": comm_score, "max": 5},
    }

    # 扣分
    penalties = 0
    penalty_items = []
    has_comfort = any(e.get("intent_id") == "ask_comfort_reassure" for e in intent_events)
    if not has_comfort and record.get("messages"):
        student_msgs = [m for m in record.get("messages", []) if m.get("role") == "student"]
        has_any_comfort = any("别" in m.get("content", "") or "放心" in m.get("content", "") for m in student_msgs)
        if not has_any_comfort:
            penalties += 2
            penalty_items.append({"reason": "对患者情绪无回应", "deduction": 2})

    allergy_asked = "allergy" in disclosed or "drug_allergy" in disclosed
    if not allergy_asked and case_data.get("difficulty", 1) <= 2:
        penalties += 2
        penalty_items.append({"reason": "未询问过敏史或用药史", "deduction": 2})

    total = sum(d["score"] for d in detail.values()) - penalties
    total = max(0, min(100, total))

    # 严重错误
    triggered = []
    for se in severe_errors:
        cond = se.get("condition", "")
        if _check_v2_severe(cond, final_level, cs_score):
            triggered.append({"code": se.get("code"), "message": se.get("message")})

    severe = len(triggered) > 0
    if severe:
        ps = "fail"
    elif total >= 90:
        ps = "excellent"
    elif total >= 80:
        ps = "good"
    elif total >= 60:
        ps = "pass"
    else:
        ps = "fail"

    return {
        "total_score": total,
        "pass_status": ps,
        "severe_error_triggered": severe,
        "severe_errors": triggered,
        "detail_scores": detail,
        "penalties": penalty_items,
        "standard_answer": {
            "triage_level": standard.get("triage_level"),
            "triage_zone": standard.get("triage_zone"),
            "disposition": standard.get("disposition", []),
        },
        "feedback": {
            "strengths": [f"{k}: {v['score']}/{v['max']}" for k, v in detail.items() if v['score'] >= v['max'] * 0.7],
            "weaknesses": [f"{k}: {v['score']}/{v['max']}" for k, v in detail.items() if v['score'] < v['max'] * 0.5],
            "penalties": penalty_items,
            "suggestions": _generate_v2_suggestions(detail, triggered, case_data),
        }
    }


def _level_diff(a, b):
    levels = {"Ⅰ级": 0, "Ⅱ级": 1, "Ⅲ级": 2, "Ⅳ级": 3}
    return abs(levels.get(a, 3) - levels.get(b, 0))


def _check_v2_severe(cond, level, cs_score):
    if not cond:
        return False
    if "Ⅳ级" in cond and level == "Ⅳ级":
        return True
    if "Ⅲ级" in cond and "Ⅳ级" in cond and level in ("Ⅲ级", "Ⅳ级"):
        return True
    if "Ⅰ级" in cond and "Ⅱ级" in cond and level in ("Ⅰ级", "Ⅱ级"):
        return True
    if "critical_signal_not_identified" in cond and cs_score < 10:
        return True
    return False


def _generate_v2_suggestions(detail, severe, case):
    parts = []
    std_fb = case.get("standard_feedback", {})
    if std_fb.get("summary"):
        parts.append(std_fb["summary"])
    weak = [k for k, v in detail.items() if v["score"] < v["max"] * 0.5]
    if weak:
        parts.append(f"需要加强: {', '.join(weak)}")
    if severe:
        parts.insert(0, "严重错误触发，必须重新训练。")
    return " ".join(parts) if parts else "请根据评分细项改进。"
