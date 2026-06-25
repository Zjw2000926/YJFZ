"""V6 120分制评分：核心100分 + 复杂情境20分"""

from services.triage_rules.engine import evaluate as rule_evaluate
from services.triage_rules.models import LEVEL_RANK

def score_triage_v6(record, case_data, queue_context=None):
    rd = rule_evaluate(case_data, record).to_dict()
    ds = record.get("disclosed_slots", [])
    mv = record.get("measured_vitals", [])
    st = record.get("timeline_state", {})

    # Core 100
    first = min(10, int(10 * len(ds) / max(len(case_data.get("dialogue_state_machine", {}).get("slots", [])), 1)))
    hist = min(15, int(15 * len(ds) / 6))
    vit = min(15, int(15 * len(mv) / max(len(case_data.get("required_measurements", [])), 1)))
    cs = 20 if rd.get("rule_hits") else 5
    lv_ok = not rd.get("under_triage")
    lv = 20 if lv_ok else max(0, 20 - (20 if rd.get("severe_error_triggered") else 10))
    disp = min(10, 5 + min(5, len(record.get("final_disposition", []))))
    ra = min(5, len(st.get("reassessments", [])) * 2)
    comm = min(5, int(5 * len(ds) / 4))
    core = {"第一眼评估": {"score": first, "max": 10}, "聚焦病史采集": {"score": hist, "max": 15},
            "生命体征评估": {"score": vit, "max": 15}, "高危信号识别": {"score": cs, "max": 20},
            "分诊等级判断": {"score": lv, "max": 20}, "处置安排": {"score": disp, "max": 10},
            "候诊复评": {"score": ra, "max": 5}, "沟通记录": {"score": comm, "max": 5}}
    core_total = sum(d["score"] for d in core.values())

    # Complex 20
    queue_pri = 0
    resource = 0
    emotion = 0
    infection = 0
    bias = 0
    if queue_context:
        pq = queue_context.get("selected_priority_order", [])
        sp = queue_context.get("standard_priority", [])
        if pq and sp:
            matches = sum(1 for i, p in enumerate(pq) if i < len(sp) and p == sp[i])
            queue_pri = min(5, int(5 * matches / max(len(sp), 1)))
        resource = min(4, len(queue_context.get("resource_allocation", {})))
    emotion = min(4, int(4 * (1 if "ask_comfort_reassure" in str(record.get("intent_events", [])) else 0.5)))
    infection = min(4, int(4 * (1 if "infectious" in str(case_data.get("critical_signals", [])).lower() else 0.5)))
    bias = min(3, 3)
    complex_scores = {"多患者优先级排序": {"score": queue_pri, "max": 5}, "资源协调": {"score": resource, "max": 4},
                      "情绪与冲突处理": {"score": emotion, "max": 4}, "感染防控与职业安全": {"score": infection, "max": 4},
                      "偏倚控制与人文关怀": {"score": bias, "max": 3}}
    complex_total = sum(d["score"] for d in complex_scores.values())

    total = core_total + complex_total
    total = max(0, min(120, total))

    severe = rd.get("severe_error_triggered", False)
    severe_codes = rd.get("severe_error_codes", [])
    if queue_context and queue_context.get("missed_critical"):
        severe = True
        severe_codes.append("MISSED_CRITICAL_IN_QUEUE")

    ps = "fail" if severe else ("excellent" if total >= 105 else "good" if total >= 90 else "pass" if total >= 70 else "fail")

    return {"total_score": total, "pass_status": ps, "severe_error_triggered": severe,
            "severe_errors": severe_codes, "core_scores": core, "complex_scores": complex_scores,
            "rule_result": rd, "standard_answer": {"triage_level": case_data.get("standard_answer", {}).get("triage_level")},
            "feedback": {"strengths": [f"{k}:{v['score']}/{v['max']}" for k, v in {**core, **complex_scores}.items() if v['score'] >= v['max'] * 0.7],
                         "weaknesses": [f"{k}:{v['score']}/{v['max']}" for k, v in {**core, **complex_scores}.items() if v['score'] < v['max'] * 0.5],
                         "suggestions": "严重错误触发，一票否决。" if severe else "请根据评分细节改进。"},
            "disclaimer": "仅用于教学训练，不用于真实临床分诊。"}
