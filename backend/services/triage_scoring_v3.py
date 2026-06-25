"""V3 评分引擎 — 集成规则引擎

评分流程：
训练记录 → 规则引擎计算最低安全等级和严重错误 → 分项得分 → 一票否决 → 规则依据反馈
"""

import json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def score_triage_v3(record: dict, case_data: dict) -> dict:
    """V3评分：规则引擎驱动的100分制评分"""
    from services.triage_rules.engine import evaluate as rule_evaluate

    result = rule_evaluate(case_data, record)
    rule_dict = result.to_dict()

    disclosed = record.get("disclosed_slots", [])
    measured = record.get("measured_vitals", [])
    state = case_data.get("dialogue_state_machine", {})
    all_slots = state.get("slots", [])
    required = [s for s in all_slots if s.get("is_required")]
    req_ms = case_data.get("required_measurements", [])

    # A. 第一眼评估 (10)
    first_score = min(10, int(10 * len(disclosed) / max(len(required), 1)))
    # B. 聚焦病史 (15)
    hist_score = min(15, int(15 * len(disclosed) / max(len(required) + 3, 1)))
    # C. 生命体征 (15)
    vital_score = min(15, int(15 * len(measured) / max(len(req_ms), 1)))
    # D. 高危信号 (20)
    cs_count = sum(1 for cs in case_data.get("critical_signals", [])
                   if any(cs.get("id", "") in str(disclosed) for _ in [1]))
    cs_score = 15 if len(rule_dict.get("rule_hits", [])) > 0 else 0
    if rule_dict.get("severe_error_triggered"):
        cs_score = 0
    # E. 分诊等级 (20)
    level_score = 20 if not rule_dict.get("under_triage") else max(0, 20 - (5 if rule_dict.get("severe_error_triggered") else 10))
    if rule_dict.get("over_triage"):
        level_score = max(0, level_score - 5)
    # F. 处置 (10)
    zone_ok = (record.get("final_zone_selected") or "") in (rule_dict.get("recommended_zone") or "")
    disp_score = 5 + (3 if zone_ok else 0) + min(2, len(record.get("final_disposition") or []))
    # G. 复评计划 (5)
    recheck = 3 if len(measured) >= len(req_ms) * 0.6 else 0
    # H. 沟通 (5)
    comm = min(5, int(5 * len(disclosed) / max(len(required), 1)))

    detail = {
        "A.第一眼评估":{"score":first_score,"max":10},
        "B.聚焦病史":{"score":hist_score,"max":15},
        "C.生命体征":{"score":vital_score,"max":15},
        "D.高危信号":{"score":cs_score,"max":20},
        "E.分诊等级":{"score":level_score,"max":20},
        "F.处置安排":{"score":min(10,disp_score),"max":10},
        "G.复评计划":{"score":recheck,"max":5},
        "H.沟通记录":{"score":comm,"max":5},
    }
    total = sum(d["score"] for d in detail.values())
    total = max(0, min(100, total))

    if rule_dict.get("severe_error_triggered"):
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
        "severe_error_triggered": rule_dict.get("severe_error_triggered"),
        "severe_errors": rule_dict.get("severe_error_codes", []),
        "detail_scores": detail,
        "rule_result": rule_dict,
        "standard_answer": {
            "triage_level": case_data.get("standard_answer", {}).get("triage_level"),
            "triage_zone": case_data.get("standard_answer", {}).get("triage_zone"),
        },
        "feedback": {
            "strengths": [f"{k}:{v['score']}/{v['max']}" for k, v in detail.items() if v['score'] >= v['max'] * 0.7],
            "weaknesses": [f"{k}:{v['score']}/{v['max']}" for k, v in detail.items() if v['score'] < v['max'] * 0.5],
            "explanations": rule_dict.get("explanations", []),
            "suggestions": "\n".join(rule_dict.get("explanations", [])) or "请根据评分细则改进。",
        }
    }
