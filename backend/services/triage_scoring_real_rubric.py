"""P0-7~P0-10: 病例专属专家 Rubric 评分服务

优先使用 case_data.scoring_rubric，规则引擎作为安全兜底。
8个固定维度，criteria级证据。
"""

from services.triage_rules.engine import evaluate as rule_evaluate
from services.triage_rules.models import LEVEL_RANK

RUBRIC_DIMENSIONS = [
    ("第一眼评估", 10), ("主诉与聚焦病史采集", 15),
    ("生命体征与客观评估", 15), ("高危信号识别", 20),
    ("分诊等级判断", 20), ("分诊处置与区域安排", 10),
    ("候诊复评与安全管理", 5), ("沟通、解释与记录", 5),
]

def _build_evidence_context(record, case_data):
    return {
        "disclosed_slots": record.get("disclosed_slots", []),
        "intent_events": record.get("intent_events", []),
        "measured_vitals": record.get("measured_vitals", []),
        "observed_items": record.get("observed_items", []),
        "final_level_selected": record.get("final_level_selected"),
        "final_zone_selected": record.get("final_zone_selected"),
        "final_disposition": record.get("final_disposition") or [],
        "timeline_state": record.get("timeline_state", {}),
    }

def score_criterion(criterion, evidence, max_score=5):
    """评分单条criterion"""
    met = False
    score = 0
    evidence_texts = []
    c_name = criterion.get("criterion", str(criterion)[:80])
    # Simple scoring: based on disclosed slots + measurements coverage
    disclosed = len(evidence.get("disclosed_slots", []))
    measured = len(evidence.get("measured_vitals", []))
    total_req = max(len(evidence.get("disclosed_slots", [])) + 3, 1)

    if disclosed > 0 and measured > 0:
        score = min(max_score, int(max_score * (disclosed + measured) / (total_req * 2)))
        met = score >= max_score * 0.5
        evidence_texts = [f"已披露{disclosed}项信息，已测量{measured}项生命体征"]

    return {"criterion": c_name, "max_score": max_score, "score": score,
            "critical_fail": criterion.get("critical_fail", False),
            "met": met, "evidence": evidence_texts,
            "missed_reason": "" if met else "信息采集或生命体征测量不足",
            "teaching_point": criterion.get("teaching_point", "建议加强该维度训练。")}

def score_triage_real_rubric(record, case_data):
    """主要 Rubric 评分入口"""
    rd = rule_evaluate(case_data, record).to_dict()
    ev = _build_evidence_context(record, case_data)
    rubric = case_data.get("scoring_rubric") or {}

    detail = {}
    criterion_scores = []
    total = 0
    disclosed_n = len(ev["disclosed_slots"])
    measured_n = len(ev["measured_vitals"])
    req_ms = case_data.get("required_measurements", [])
    ms_total = len(req_ms)

    for dim_name, dim_max in RUBRIC_DIMENSIONS:
        # P0-C: 正确读取 scoring_rubric.items (不是 dimensions)
        dim_criteria = []
        dim_real_max = dim_max
        if rubric:
            for item in rubric.get("items", []):
                if item.get("dimension") == dim_name:
                    dim_criteria = item.get("criteria", [])
                    dim_real_max = item.get("max_score", dim_max)
                    break

        if dim_criteria:
            dim_score = 0
            for crit in dim_criteria:
                cs = score_criterion(crit, ev, crit.get("max_score", dim_max // max(len(dim_criteria), 1)))
                criterion_scores.append(cs)
                dim_score += cs["score"]
            dim_score = min(dim_max, dim_score)
        else:
            # Fallback scoring
            if "第一眼" in dim_name:
                dim_score = min(dim_max, int(dim_max * measured_n / max(ms_total, 1)))
            elif "病史" in dim_name or "主诉" in dim_name:
                dim_score = min(dim_max, int(dim_max * disclosed_n / 6))
            elif "生命体征" in dim_name:
                dim_score = min(dim_max, int(dim_max * measured_n / max(ms_total, 1)))
            elif "高危" in dim_name:
                dim_score = dim_max if rd.get("rule_hits") else int(dim_max * 0.3)
            elif "分诊等级" in dim_name:
                dim_score = dim_max if not rd.get("under_triage") else max(0, dim_max - 10)
            elif "处置" in dim_name:
                dim_score = min(dim_max, int(dim_max * 0.6))
            elif "复评" in dim_name:
                ra_count = len(ev["timeline_state"].get("reassessments", []))
                dim_score = min(dim_max, ra_count * 2)
            else:
                dim_score = min(dim_max, int(dim_max * disclosed_n / 5))

        detail[dim_name] = {"score": dim_score, "max": dim_real_max, "criteria": dim_criteria}
        total += dim_score

    total = max(0, min(100, total))

    # P0-9: Severe errors + one-vote veto
    critical_failures = [cs for cs in criterion_scores if cs.get("critical_fail") and not cs["met"]]
    severe = rd.get("severe_error_triggered", False) or len(critical_failures) > 0
    se_codes = rd.get("severe_error_codes", [])
    if critical_failures:
        se_codes.extend([cf["criterion"] for cf in critical_failures])

    effective = min(59, total) if severe else total
    ps = "fail" if severe else ("excellent" if total >= 90 else "good" if total >= 80 else "pass" if total >= 60 else "fail")

    return {
        "total_score": total, "effective_score": effective,
        "pass_status": ps, "severe_error_triggered": severe,
        "severe_errors": se_codes, "detail_scores": detail,
        "criterion_scores": criterion_scores,
        "critical_failures": [cf for cf in critical_failures],
        "rule_result": rd,
        "standard_answer": {"triage_level": case_data.get("standard_answer", {}).get("triage_level"),
                            "triage_zone": case_data.get("standard_answer", {}).get("triage_zone"),
                            "disposition": case_data.get("standard_answer", {}).get("disposition", [])},
        "feedback": _build_expert_feedback(record, case_data, total, effective, severe, critical_failures, rd, ev),
        "scoring_version": "real_rubric_v1",
        "rubric_version": rubric.get("version", "real_triage_case_library"),
    }

def _as_list(value):
    if value is None: return []
    if isinstance(value, list): return value
    if isinstance(value, str): return [value]
    return [str(value)]

def _build_expert_feedback(record, case_data, total, effective, severe, critical_failures, rd, ev):
    """P0-11 + P0-G: 专家型教学反馈"""
    fb = case_data.get("feedback") or {}
    red_flags = _as_list(case_data.get("red_flags", []))
    disclosed = ev["disclosed_slots"]
    measured = ev["measured_vitals"]
    req_ms = case_data.get("required_measurements", [])

    correct = _as_list(fb.get("correct_points"))
    risks = _as_list(fb.get("risk_if_missed"))
    key_rf = _as_list(fb.get("key_red_flag")) or red_flags[:3]
    reason = fb.get("reason_for_triage_level", "") or ""
    logic = fb.get("correct_triage_logic", "") or ""
    remediation = _as_list(fb.get("recommended_remediation"))

    # Student-specific additions
    missed_qs = [s.get("label", s) for s in case_data.get("dialogue_state_machine", {}).get("slots", [])
                 if s.get("slot_id") not in disclosed][:5]
    missed_ms = [m.get("label", m.get("id")) for m in req_ms if m.get("id") not in measured][:5]
    missed_rf = [r for r in red_flags[:5] if not any(str(r) in str(d) for d in disclosed)][:3]

    safety_errors = []
    if severe:
        safety_errors = [f"一票否决: {cf.get('criterion', cf)}" for cf in critical_failures[:3]]
        safety_errors.extend(rd.get("severe_error_codes", [])[:2])

    next_focus = []
    if missed_qs: next_focus.append("补全问诊: " + ", ".join(missed_qs[:3]))
    if missed_ms: next_focus.append("补全测量: " + ", ".join(missed_ms[:3]))
    if severe: next_focus.append("重训本病例，注意高危信号和分诊等级")

    return {
        "correct_points": correct if correct else (["完成训练"] if total >= 60 else []),
        "risk_if_missed": risks if risks else (["高危信号未识别将导致患者安全风险"] if missed_rf else []),
        "key_red_flag": key_rf,
        "reason_for_triage_level": reason or "根据病例标准分诊等级判定",
        "correct_triage_logic": logic or "",
        "recommended_remediation": remediation if remediation else next_focus,
        "missed_required_questions": missed_qs,
        "missed_measurements": missed_ms,
        "missed_red_flags": missed_rf,
        "decision_errors": safety_errors,
        "safety_critical_errors": safety_errors,
        "next_practice_focus": next_focus if next_focus else ["继续训练提升综合分诊能力"],
    }
