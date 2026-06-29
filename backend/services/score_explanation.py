"""Build clickable, evidence-based score explanations.

The score shown in the report must be internally consistent: every displayed
sub-criterion is derived from the same operation evidence that determines the
dimension score. This avoids the confusing state where all evidence cards look
completed while the dimension still loses points.
"""

from __future__ import annotations

from typing import Any

from services.case_types import is_dynamic_case
from services.feedback_evidence import (
    canonical_measurement,
    covered_slot_groups,
    detect_record_groups,
    filter_missed_slots,
)
from services.report_generator import event_indicates_deterioration, record_has_triggered_deterioration, student_recognized_deterioration
from services.triage_rules.models import LEVEL_RANK


SCORE_EXPLANATION_VERSION = "criteria_v4_dynamic_consistency"

VITAL_ALIASES = {
    "temperature": {"temperature", "temperature_c", "body_temperature", "temp"},
    "heart_rate": {"heart_rate", "heart_rate_bpm", "pulse", "pulse_rate", "hr"},
    "blood_pressure": {
        "blood_pressure",
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "systolic_bp",
        "diastolic_bp",
        "bp",
    },
    "respiratory_rate": {"respiratory_rate", "respiratory_rate_bpm", "rr", "respiration"},
    "spo2": {"spo2", "spo2_percent", "oxygen_saturation", "spo2_percentage"},
    "pain_score": {"pain_score", "nrs", "nrs_score", "pain_nrs", "pain"},
    "consciousness": {"consciousness", "gcs", "gcs_score", "mental_status", "avpu"},
    "blood_glucose": {"blood_glucose", "blood_glucose_mmol_l", "glucose"},
}

CRITICAL_VITALS = {
    "heart_rate": "心率",
    "blood_pressure": "血压",
    "respiratory_rate": "呼吸",
    "spo2": "SpO2",
    "pain_score": "疼痛评分",
    "consciousness": "意识状态",
}


def enrich_score_result(record: dict[str, Any], case_data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Attach explanatory criteria to every score dimension.

    Existing scores remain authoritative. The generated criteria are used for
    review, feedback, and UI drill-down.
    """
    if not isinstance(result, dict):
        return result
    detail_scores = result.get("detail_scores") or {}
    if not isinstance(detail_scores, dict):
        return result

    rule_result = result.get("rule_result") or {}
    context = _build_context(record, case_data, rule_result)
    enriched: dict[str, Any] = {}
    all_criteria: list[dict[str, Any]] = []

    for index, (name, dim) in enumerate(detail_scores.items()):
        if not isinstance(dim, dict):
            continue
        max_score = max(_as_number(dim.get("max"), 0), 1)
        kind = _classify_dimension(name, index)
        criteria = _build_dimension_criteria(kind, name, max_score, context)
        criteria = _reconcile_criteria_scores(criteria, max_score)
        original_score = _as_number(dim.get("score"), 0)
        score = _criteria_total(criteria, original_score, max_score)
        enriched_dim = {
            **dim,
            "dimension_id": kind,
            "name": name,
            "score": score,
            "original_score": original_score,
            "max": max_score,
            "lost_score": max(0, round(max_score - score, 2)),
            "status": _score_status(score, max_score),
            "summary": _dimension_summary(name, score, max_score, criteria),
            "criteria": criteria,
            "deduction_reasons": [c["deduction_reason"] for c in criteria if c.get("deduction_reason")],
            "evidence": [c["evidence"] for c in criteria if c.get("evidence")],
            "standard_basis": _dimension_basis(kind, context),
            "international_reference": _international_reference(kind),
            "improvement": _dimension_improvement(kind, criteria),
        }
        enriched[name] = enriched_dim
        all_criteria.extend({**c, "dimension": name, "dimension_id": kind} for c in criteria)

    if result.get("criterion_scores"):
        result["raw_criterion_scores"] = result.get("criterion_scores")
    result["detail_scores"] = enriched
    result["score_explanations"] = list(enriched.values())
    result["criterion_scores"] = all_criteria
    result["score_explanation_version"] = SCORE_EXPLANATION_VERSION
    _recalculate_total_from_dimensions(result, enriched)
    if result.get("timeline_report"):
        result["timeline_report"]["score_breakdown"] = enriched
    return result


def _reconcile_criteria_scores(criteria: list[dict[str, Any]], max_score: float) -> list[dict[str, Any]]:
    """Scale criterion weights to the dimension max and refresh statuses."""
    if not criteria:
        return criteria
    total_max = sum(_as_number(c.get("max"), 0) for c in criteria)
    if total_max <= 0:
        return criteria
    scale = max_score / total_max
    reconciled = []
    for item in criteria:
        updated = {**item}
        new_max = round(_as_number(item.get("max"), 0) * scale, 2)
        new_score = round(min(new_max, _as_number(item.get("score"), 0) * scale), 2)
        updated["max"] = new_max
        updated["max_score"] = new_max
        updated["score"] = new_score
        if new_score <= 0:
            updated["status"] = "missed"
            updated["met"] = False
        elif new_score < new_max * 0.8:
            updated["status"] = "partial"
        elif updated.get("met"):
            updated["status"] = "complete"
        else:
            updated["status"] = "partial"
        reconciled.append(updated)
    return reconciled


def _criteria_total(criteria: list[dict[str, Any]], fallback: float, max_score: float) -> float:
    if not criteria:
        return round(max(0, min(fallback, max_score)), 2)
    return round(max(0, min(sum(_as_number(c.get("score"), 0) for c in criteria), max_score)), 2)


def _recalculate_total_from_dimensions(result: dict[str, Any], enriched: dict[str, Any]) -> None:
    total = round(sum(_as_number(dim.get("score"), 0) for dim in enriched.values()), 2)
    total = max(0, min(100, total))
    result["total_score"] = total
    severe = bool(result.get("severe_error_triggered") or result.get("serious_error_triggered"))
    result["effective_score"] = min(59, total) if severe else total
    if severe:
        result["pass_status"] = "fail"
        result["final_result"] = "fail"
    else:
        result["pass_status"] = "excellent" if total >= 90 else "good" if total >= 80 else "pass" if total >= 60 else "fail"
        result["final_result"] = "pass" if total >= 60 else "fail"
    if result.get("timeline_report"):
        result["timeline_report"]["total_score"] = total
        result["timeline_report"]["passed"] = result["pass_status"] != "fail"


def _build_context(record: dict[str, Any], case_data: dict[str, Any], rule_result: dict[str, Any]) -> dict[str, Any]:
    actions = record.get("student_actions") or []
    legacy_actions = record.get("actions") or []
    action_types = {a.get("action_type") for a in actions if a.get("action_type")}
    action_types.update(a.get("action_type") for a in legacy_actions if a.get("action_type"))

    measured = {str(item) for item in (record.get("measured_vitals") or []) if item}
    for item in record.get("vital_measurement_log") or []:
        measured.update(str(mid) for mid in (item.get("measurement_ids") or []) if mid)
    for action in legacy_actions:
        payload = action.get("payload") or {}
        measured.update(str(mid) for mid in (payload.get("measurement_ids") or []) if mid)

    triage_decisions = record.get("triage_decisions") or []
    init_decision = next((d for d in triage_decisions if d.get("decision_type") == "initial"), None)
    reassessment_decisions = [d for d in triage_decisions if d.get("decision_type") == "reassessment"]
    final_decision = reassessment_decisions[-1] if reassessment_decisions else init_decision
    state = record.get("timeline_state") or {}
    required_measurements = _required_measurements(case_data)
    slots = case_data.get("dialogue_state_machine", {}).get("slots", []) or []
    disclosed_slots = set(record.get("disclosed_slots") or [])
    intent_events = record.get("intent_events") or []
    question_count = len([m for m in record.get("messages") or [] if m.get("role") == "student"])
    observed_items = set(record.get("observed_items") or [])
    vital_log = record.get("vital_measurement_log") or []
    notes = record.get("notes") or []
    notification_events = record.get("notification_events") or []
    deterioration = record_has_triggered_deterioration(record)
    triage_reason = record.get("triage_reason") or record.get("decision_reason") or ""
    if not triage_reason:
        for decision in reversed(triage_decisions):
            if decision.get("reason"):
                triage_reason = decision.get("reason")
                break

    return {
        "record": record,
        "case": case_data,
        "rule_result": rule_result,
        "actions": actions,
        "action_types": action_types,
        "measured": measured,
        "measured_canonical": _canonical_vitals(measured),
        "required_measurements": required_measurements,
        "slots": slots,
        "disclosed_slots": disclosed_slots,
        "intent_events": intent_events,
        "question_count": question_count,
        "observed_items": observed_items,
        "triage_decisions": triage_decisions,
        "init_decision": init_decision,
        "reassessment_decisions": reassessment_decisions,
        "final_decision": final_decision,
        "state": state,
        "vital_log": vital_log,
        "notes": notes,
        "notification_events": notification_events,
        "deterioration": deterioration,
        "is_dynamic_case": is_dynamic_case(case_data),
        "triage_reason": str(triage_reason or ""),
        "recognized_deterioration": student_recognized_deterioration(record),
        "standard_initial_level": case_data.get("standard_initial_triage_level")
        or case_data.get("standard_answer", {}).get("triage_level"),
        "standard_initial_area": case_data.get("standard_initial_area")
        or case_data.get("standard_answer", {}).get("triage_zone"),
        "standard_final_level": case_data.get("standard_final_triage_level")
        or case_data.get("standard_answer", {}).get("triage_level"),
        "standard_final_area": case_data.get("standard_final_area")
        or case_data.get("standard_answer", {}).get("triage_zone"),
        "red_flags": _red_flags(case_data),
        "history_groups": detect_record_groups(record),
        "covered_slot_groups": covered_slot_groups(case_data, record, list(disclosed_slots)),
        "missed_history_slots": filter_missed_slots(case_data, record, list(disclosed_slots)),
    }


def _build_dimension_criteria(kind: str, name: str, max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    if kind == "first_look":
        return _first_look_criteria(max_score, ctx)
    if kind == "history":
        return _history_criteria(max_score, ctx)
    if kind == "vitals":
        return _vitals_criteria(max_score, ctx)
    if kind == "risk":
        return _risk_criteria(max_score, ctx)
    if kind == "triage_level":
        return _triage_level_criteria(max_score, ctx)
    if kind == "disposition":
        return _disposition_criteria(max_score, ctx)
    if kind == "safety_management":
        return _safety_management_criteria(max_score, ctx)
    if kind == "reassessment_time":
        return _reassessment_time_criteria(max_score, ctx)
    if kind == "reassessment_content":
        return _reassessment_content_criteria(max_score, ctx)
    if kind == "deterioration_upgrade":
        return _deterioration_upgrade_criteria(max_score, ctx)
    if kind == "communication":
        return _communication_criteria(max_score, ctx)
    return [_criterion("overall", "综合评分项", max_score, max_score, True, "已按病例评分规则完成综合评分", "", _dimension_basis(kind, ctx), "继续对照病例标准答案复盘。", kind)]


def _first_look_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    observed = bool(ctx["observed_items"]) or "observe_patient" in ctx["action_types"]
    measured_abc = bool(ctx["measured_canonical"].intersection({"consciousness", "respiratory_rate", "spo2", "blood_pressure"}))
    return [
        _criterion("appearance", "观察患者外观、痛苦表情和体位", max_score * 0.4, max_score * 0.4 if observed else 0, observed, "已记录第一眼观察", "未记录第一眼观察，无法证明已快速识别患者初始状态", "预检分诊首先要进行第一眼评估，识别是否存在立即威胁生命的表现。", "进入病例后先观察外观、意识、呼吸、皮肤灌注和明显痛苦表现。", "first_look"),
        _criterion("abc", "关注意识、呼吸、循环等立即风险", max_score * 0.35, max_score * 0.35 if measured_abc else 0, measured_abc, "已测量或记录意识/呼吸/循环相关项目", "未见意识、呼吸或循环风险相关评估证据", "ESI/ATS/CTAS均强调先识别复苏或高危患者。", "第一眼评估要覆盖意识、呼吸、循环和皮肤灌注。", "first_look"),
        _criterion("timing", "在最终分诊前完成初始观察", max_score * 0.25, max_score * 0.25 if observed or ctx["question_count"] else 0, observed or ctx["question_count"] > 0, "已在问诊/测量前后形成初始评估证据", "缺少早期评估证据", "教学病例要求先形成初始危急程度判断，再进入详细问诊和测量。", "提交前补齐第一眼评估记录。", "first_look"),
    ]


def _history_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    slots = ctx["slots"]
    required_slots = [s for s in slots if s.get("is_required")]
    slot_total = max(len(required_slots) or len(slots), 1)
    covered_group_map = ctx.get("covered_slot_groups") or {}
    groups = set(ctx.get("history_groups") or set()) | set(covered_group_map.keys())
    covered_slot_labels = sorted({label for labels in covered_group_map.values() for label in labels})
    slot_hits = len(covered_slot_labels)

    chief_items = [
        ("主诉/部位", "chief_complaint_location"),
        ("起病时间", "onset_time"),
        ("性质/程度", ("pain_quality", "severity", "radiation")),
    ]
    chief_met = _met_history_items(chief_items, groups)
    chief_score_ratio = _ratio(chief_met, len(chief_items))
    chief_ok = chief_score_ratio >= 0.8

    broad_items = [
        ("伴随症状", "accompanying"),
        ("既往史/危险因素", "history_risk"),
        ("用药史", "medication"),
        ("过敏史", "allergy"),
    ]
    if _case_has_group(slots, "similar_episode"):
        broad_items.append(("类似发作", "similar_episode"))
    broad_met = _met_history_items(broad_items, groups)
    broad_score_ratio = _ratio(broad_met, len(broad_items))
    broad_ok = broad_score_ratio >= 0.8

    change_items = [("症状变化/诱因/趋势", "symptom_change")]
    if ctx["red_flags"] or _case_has_group(slots, "history_risk"):
        change_items.append(("高危相关背景", "history_risk"))
    if _case_has_group(slots, "similar_episode"):
        change_items.append(("既往类似发作", "similar_episode"))
    change_met = _met_history_items(change_items, groups)
    change_score_ratio = _ratio(change_met, len(change_items))
    change_ok = change_score_ratio >= 0.8

    missed = ctx.get("missed_history_slots") or _missed_slot_labels(slots, ctx["disclosed_slots"], 5)
    return [
        _criterion(
            "chief_complaint",
            "采集主诉、起病时间、部位和程度",
            max_score * 0.4,
            max_score * 0.4 * chief_score_ratio,
            chief_ok,
            _history_evidence("已覆盖", chief_met, chief_items, ctx, slot_hits, slot_total),
            _history_deduction("主诉/起病时间/症状细节采集不足", chief_met, chief_items),
            "病例标准答案要求围绕主诉和症状变化进行聚焦问诊。",
            "至少确认起病时间、部位、性质、程度和变化趋势。",
            "history",
        ),
        _criterion(
            "associated_history",
            "询问伴随症状、既往史、用药/过敏史",
            max_score * 0.35,
            max_score * 0.35 * broad_score_ratio,
            broad_ok,
            _history_evidence("已覆盖", broad_met, broad_items, ctx, slot_hits, slot_total),
            _history_deduction("病史覆盖不完整", broad_met, broad_items, missed),
            "ESI/CTAS/MTS等分诊框架均要求用症状和危险因素判断紧急程度。",
            "补问伴随症状、既往史、用药史、过敏史和特殊人群信息。",
            "history",
        ),
        _criterion(
            "change_trend",
            "确认症状变化和高危相关背景",
            max_score * 0.25,
            max_score * 0.25 * change_score_ratio,
            change_ok,
            _history_evidence("已覆盖", change_met, change_items, ctx, slot_hits, slot_total),
            _history_deduction("未充分确认症状变化或危险因素", change_met, change_items),
            "动态病例尤其需要关注症状是否加重；高危病例需同时核实相关危险背景。",
            "把“是否加重、诱因、是否伴随冷汗/头晕/放射痛/气短、既往高危背景”等作为固定追问。",
            "history",
        ),
    ]


def _met_history_items(items: list[tuple[str, Any]], groups: set[str]) -> list[str]:
    met = []
    for label, group_spec in items:
        if isinstance(group_spec, tuple):
            if any(group in groups for group in group_spec):
                met.append(label)
        elif group_spec in groups:
            met.append(label)
    return met


def _ratio(met: list[Any], total: int) -> float:
    if total <= 0:
        return 1.0
    return round(max(0, min(len(met) / total, 1)), 4)


def _case_has_group(slots: list[dict[str, Any]], group: str) -> bool:
    keywords = {
        "similar_episode": ("类似", "以前", "发作过", "这种情况", "ask_similar_episode"),
        "history_risk": ("既往", "病史", "高血压", "糖尿病", "冠心病", "吸烟", "ask_past_history", "ask_smoking_alcohol"),
    }.get(group, (group,))
    for slot in slots or []:
        text = " ".join(
            str(value)
            for value in [
                slot.get("slot_id", ""),
                slot.get("label", ""),
                " ".join(map(str, slot.get("canonical_intents") or [])),
                " ".join(map(str, slot.get("answer_facts") or [])),
            ]
        )
        if any(keyword in text for keyword in keywords):
            return True
    return False


def _history_evidence(prefix: str, met: list[str], items: list[tuple[str, Any]], ctx: dict[str, Any], slot_hits: int, slot_total: int) -> str:
    missing = _missing_history_labels(met, items)
    covered = "、".join(met) if met else "无"
    message = f"{prefix}: {covered}；问诊{ctx['question_count']}次，关键病史证据{slot_hits}/{slot_total}项"
    if missing:
        message += f"；缺少: {'、'.join(missing)}"
    return message


def _history_deduction(prefix: str, met: list[str], items: list[tuple[str, Any]], missed_slots: list[str] | None = None) -> str:
    missing = _missing_history_labels(met, items)
    details = missing or (missed_slots or [])[:5]
    if details:
        return f"{prefix}: 缺少{'、'.join(details)}"
    return prefix


def _missing_history_labels(met: list[str], items: list[tuple[str, Any]]) -> list[str]:
    met_set = set(met)
    return [label for label, _ in items if label not in met_set]


def _vitals_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    measured = ctx["measured"]
    measured_canonical = ctx["measured_canonical"]
    required = ctx["required_measurements"]
    required_ids = {_canonical_vital(m["id"]) for m in required}
    missing_required = [m["label"] for m in required if _canonical_vital(m["id"]) not in measured_canonical][:6]
    critical_missing = [label for vid, label in CRITICAL_VITALS.items() if vid not in measured_canonical]
    complete_required = bool(required_ids) and required_ids.issubset(measured_canonical)
    critical_complete = len(critical_missing) == 0
    deterioration_recheck = _has_rechecked_after_deterioration(ctx)
    needs_recheck = ctx["is_dynamic_case"] and ctx["deterioration"]
    initial_weight = 0.55 if not needs_recheck else 0.4
    critical_weight = 0.45 if not needs_recheck else 0.35
    criteria = [
        _criterion("initial_vitals", "完成病例要求的初始生命体征测量", max_score * initial_weight, max_score * initial_weight if complete_required else max_score * initial_weight * 0.5 if measured else 0, complete_required, f"已测量: {', '.join(sorted(measured)) or '无'}", "生命体征测量不完整" + (f": 缺少{', '.join(missing_required)}" if missing_required else ""), "生命体征是分诊紧急度和病情趋势判断的客观依据。", "补齐病例要求的客观评估项目。", "vitals"),
        _criterion("critical_vitals", "覆盖关键客观指标: HR/BP/RR/SpO2/NRS/意识", max_score * critical_weight, max_score * critical_weight if critical_complete else max_score * critical_weight * 0.4 if measured else 0, critical_complete, "已覆盖关键客观指标" if critical_complete else f"缺少: {', '.join(critical_missing[:5])}", "关键生命体征缺项会影响低估分诊风险判断", "ESI和多数量表均把生命体征异常、意识改变、低氧、休克趋势视为高危线索。", "补齐 HR、BP、RR、SpO2、NRS、意识等关键客观指标。", "vitals"),
    ]
    if needs_recheck:
        criteria.append(_criterion("dynamic_recheck", "病情变化后重新测量生命体征", max_score * 0.25, max_score * 0.25 if deterioration_recheck else 0, deterioration_recheck, "恶化后已有复测记录" if deterioration_recheck else "恶化后未见复测记录", "患者恶化后未见重新测量生命体征记录", "候诊期间状态变化后必须重新评估客观指标，不能沿用初始生命体征。", "T15/T30 或症状加重后重新测 HR、BP、RR、SpO2、疼痛评分。", "vitals"))
    return criteria


def _risk_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    hits = ctx["rule_result"].get("rule_hits") or []
    under = bool(ctx["rule_result"].get("under_triage"))
    red_flags = ctx["red_flags"]
    reasoned = bool(ctx.get("triage_reason", "").strip())
    red_flag_met = bool(red_flags and (hits or ctx["question_count"] >= 2 or reasoned)) or not red_flags
    recognized = bool(hits) or ctx["recognized_deterioration"]
    return [
        _criterion("rule_hits", "识别规则引擎命中的高危线索", max_score * 0.45, max_score * 0.45 if hits else 0, bool(hits), _rule_hit_evidence(hits), "未形成可追溯的高危规则命中证据", "系统以病例标准答案和规则引擎判定高危信号，LLM不参与自由判分。", "问诊和测量后主动归纳冷汗、放射痛、低氧、血压下降、意识改变等红旗。", "risk"),
        _criterion("red_flags", "覆盖病例红旗信号", max_score * 0.35, max_score * 0.35 if red_flag_met else max_score * 0.15 if red_flags else max_score * 0.35, red_flag_met, (f"病例红旗: {', '.join(red_flags[:5])}" + (f"；分诊理由: {ctx['triage_reason'][:60]}" if reasoned else "")) if red_flags else "本病例未配置额外红旗", "未充分追问或识别病例红旗信号", "胸痛、卒中、休克、低氧、孕产妇/儿童等高危线索应提升分诊警觉。", "在训练界面的分诊理由/高危信号记录中写明关键红旗。", "risk"),
        _criterion("avoid_undertriage", "避免低估分诊风险", max_score * 0.2, 0 if under else max_score * 0.2, not under, "规则引擎未提示低估分诊" if not under else "规则引擎提示存在低估分诊", "存在低估分诊风险", "五级分诊系统的核心安全目标之一是减少低估分诊。", "若高危信号存在，分诊等级不能低于规则最低等级。", "risk"),
    ]


def _triage_level_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    init = ctx["init_decision"]
    final = ctx["final_decision"]
    init_level = (init or {}).get("level") or ctx["record"].get("final_level_selected")
    final_level = (final or {}).get("level") or ctx["record"].get("final_level_selected")
    init_accuracy = _level_accuracy(init_level, ctx["standard_initial_level"], max_score * 0.4)
    final_accuracy = _level_accuracy(final_level, ctx["standard_final_level"], max_score * 0.4)
    under = bool(ctx["rule_result"].get("under_triage"))
    over = bool(ctx["rule_result"].get("over_triage"))
    return [
        _criterion("initial_level", "初始分诊等级与病例标准一致", max_score * 0.4, init_accuracy["score"], init_accuracy["met"], f"学员初始: {init_level or '未记录'}；标准: {ctx['standard_initial_level'] or '未配置'}", init_accuracy["deduction"], "分诊等级必须由病例标准答案和规则引擎判定，不能由LLM自由判断。", "对照高危信号和生命体征，避免低估；如提高等级，也要写清理由并匹配区域。", "triage_level", warning=init_accuracy["warning"]),
        _criterion("final_level", "最终/复评分诊等级符合恶化后的标准", max_score * 0.4, final_accuracy["score"], final_accuracy["met"], f"学员最终: {final_level or '未记录'}；标准: {ctx['standard_final_level'] or '未配置'}", final_accuracy["deduction"], "动态病例恶化后应重新判定分诊等级。", "患者恶化后若达到更高等级标准，应升级并记录重新分诊。", "triage_level", warning=final_accuracy["warning"]),
        _criterion("triage_bias", "无明显低估/过度分诊", max_score * 0.2, max_score * 0.2 if not under and not over else max_score * 0.08 if over else 0, not under and not over, "无明显低估或过度分诊" if not under and not over else "存在过度分诊提示" if over else "存在低估分诊提示", "存在低估或过度分诊，说明等级判断与标准不一致", "ESI/ATS/CTAS均强调按紧急程度分层，低估会延误处置，过度分诊也需有依据并匹配流程。", "先保证不低估危重程度，再按病例标准、资源需求和区域安排保持一致。", "triage_level", warning=over),
    ]


def _disposition_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    area = (ctx["final_decision"] or {}).get("area") or ctx["record"].get("final_zone_selected")
    final_level = (ctx["final_decision"] or {}).get("level") or ctx["record"].get("final_level_selected")
    area_ok = _area_matches_standard(area, ctx["standard_final_area"], final_level)
    area_consistent = _level_area_consistent(final_level, area)
    final_disposition = ctx["record"].get("final_disposition") or []
    notified = _doctor_notified(ctx, timely=ctx["deterioration"])
    needs_notify = ctx["deterioration"] or _level_rank(ctx["standard_final_level"]) <= 2
    noted = bool(ctx.get("triage_reason")) or bool(ctx["notes"])
    return [
        _criterion("area", "就诊区域与分诊等级匹配", max_score * 0.45, max_score * 0.45 if (area_ok and area_consistent) else max_score * 0.18 if area_ok else 0, area_ok and area_consistent, f"学员区域: {area or '未记录'}；标准区域: {ctx['standard_final_area'] or '未配置'}；等级: {final_level or '未记录'}", "区域安排与病例标准或所选等级不一致", "区域安排应与分诊等级和病情风险匹配；Ⅰ级不能安排黄区或绿区候诊。", "Ⅰ级进入红区/抢救区；Ⅱ级胸痛等高危病例进入红区或专病绿色通道/优先处置区，避免写成普通绿区。", "disposition"),
        _criterion("notify", "需要时通知医生或启动优先流程", max_score * 0.35, max_score * 0.35 if (not needs_notify or notified) else 0, (not needs_notify or notified), "已通知医生/勾选通知" if notified else "未见通知医生记录", "高危或恶化后未通知医生", "危重化、低氧、休克趋势、心源性胸痛风险等应及时通知医生。", "在分诊处置中明确记录通知医生和区域调整。", "disposition"),
        _criterion("waiting_safety", "等待安排与安全观察", max_score * 0.2, max_score * 0.2 if ctx["init_decision"] or final_disposition or noted else 0, bool(ctx["init_decision"] or final_disposition or noted), "已有分诊决策/处置/记录说明" if (ctx["init_decision"] or final_disposition or noted) else "未见处置或记录说明", "缺少等待或处置安排记录", "候诊患者应有安全观察和复评计划。", "在处置勾选或记录说明中写明候诊观察、复评时间和异常报告要求。", "disposition"),
    ]


def _safety_management_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Score waiting safety without forcing dynamic reassessment onto static emergency cases."""
    if ctx["is_dynamic_case"]:
        return _reassessment_time_criteria(max_score, ctx)
    area = (ctx["final_decision"] or {}).get("area") or ctx["record"].get("final_zone_selected")
    final_disposition = ctx["record"].get("final_disposition") or []
    not_waiting = (
        "红" in str(area)
        or any("红区" in str(item) or "绿色通道" in str(item) or str(item) == "notify_doctor" or "通知医生" in str(item) for item in final_disposition)
    )
    monitored = bool(ctx["measured_canonical"].intersection({"blood_pressure", "heart_rate", "respiratory_rate", "spo2", "consciousness"}))
    notified = _doctor_notified(ctx)
    noted = "record_note" in ctx["action_types"] or bool(ctx["notes"]) or bool(ctx.get("triage_reason"))
    return [
        _criterion(
            "no_waiting",
            "明确不安排普通候诊",
            max_score * 0.4,
            max_score * 0.4 if not_waiting else 0,
            not_waiting,
            f"区域/处置记录: {area or '未记录'}；{', '.join(map(str, final_disposition)) or '未记录'}",
            "未体现不候诊或红区优先处置",
            "该静态病例为立即高危/Ⅰ级场景，标准要求进入红区或优先处置，而不是候诊后复评。",
            "Ⅰ级或循环不稳定患者应直接进入红区/抢救流程，不按普通候诊复评处理。",
            "safety_management",
        ),
        _criterion(
            "continuous_monitoring",
            "连续观察生命体征和意识",
            max_score * 0.35,
            max_score * 0.35 if monitored else 0,
            monitored,
            f"已测量: {', '.join(sorted(ctx['measured'])) or '无'}",
            "未见连续观察所需的关键生命体征/意识评估证据",
            "静态高危病例的安全管理重点是立即监测和交接，而不是等待到复评时间。",
            "至少完成血压、心率、呼吸、SpO2、意识/皮肤灌注等关键评估。",
            "vitals",
        ),
        _criterion(
            "rapid_response_record",
            "记录变化并及时响应/通知医生",
            max_score * 0.25,
            max_score * 0.25 if (notified or noted) else 0,
            notified or noted,
            "已通知医生或保存记录说明" if (notified or noted) else "未见通知医生或记录说明",
            "未记录关键响应、通知医生或交接说明",
            "Ⅰ级/Ⅱ级高危患者需要可追溯的通知医生、抢救流程或SBAR交接记录。",
            "提交时勾选通知医生/绿色通道，并记录关键生命体征和交接说明。",
            "communication",
        ),
    ]


def _reassessment_time_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    init = ctx["init_decision"] or {}
    minutes = init.get("reassessment_minutes")
    set_any = isinstance(minutes, int) and minutes > 0
    expected_max = _expected_reassessment_minutes(ctx)
    reasonable = set_any and minutes <= expected_max
    partially_reasonable = set_any and minutes <= max(30, expected_max)
    on_time = bool(ctx["state"].get("reassessment_on_time")) or (
        bool(ctx["state"].get("reassessment_completed")) and not bool(ctx["state"].get("reassessment_overdue"))
    )
    needs_reassessment = ctx["is_dynamic_case"] and (
        ctx["deterioration"] or _level_rank(ctx["standard_initial_level"]) <= 3
    )
    return [
        _criterion("set_interval", "初始分诊后设置复评时间", max_score * 0.45, max_score * 0.45 if set_any else 0, set_any, f"设置复评: {minutes}分钟" if set_any else "未设置复评时间", "未设置复评时间", "III级候诊患者应设置短时间复评，症状变化应提前复评。", "初始分诊为III级或动态病例时设置30分钟内复评。", "reassessment_time"),
        _criterion("reasonable_interval", "复评间隔合理", max_score * 0.3, max_score * 0.3 if (not needs_reassessment or reasonable) else max_score * 0.15 if partially_reasonable else 0, (not needs_reassessment or reasonable), f"复评间隔{minutes}分钟；本病例建议不超过{expected_max}分钟" if set_any else f"无复评间隔；本病例建议不超过{expected_max}分钟", "复评间隔过长或未按病例标准等级设置", "ATS/CTAS类时间敏感分诊框架强调按紧急程度控制等待和复评。", "按病例标准等级设置复评，Ⅱ级或高危胸痛通常需更短时间内复评/优先处置，而不是按学员误选等级放宽。", "reassessment_time"),
        _criterion("on_time", "按时或提前复评", max_score * 0.25, max_score * 0.25 if (not needs_reassessment or on_time or ctx["reassessment_decisions"]) else 0, (not needs_reassessment or on_time or bool(ctx["reassessment_decisions"])), "已有复评记录" if ctx["reassessment_decisions"] else "未见复评记录", "未按复评要求完成候诊复评", "患者候诊期间状态变化后应重新评估。", "到达复评时间或症状加重时立即复评。", "reassessment_time"),
    ]


def _reassessment_content_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    reassessed = "reassess" in ctx["action_types"] or bool(ctx["reassessment_decisions"])
    recheck_quality = _recheck_quality(ctx)
    remeasured = recheck_quality >= 0.8
    symptom_review = reassessed or ctx["question_count"] >= 2
    return [
        _criterion("perform_reassessment", "执行候诊复评", max_score * 0.35, max_score * 0.35 if reassessed else 0, reassessed, "已记录复评动作" if reassessed else "未记录复评动作", "未执行候诊复评", "动态病例评分强调过程复评，而不只看最终等级。", "主动点击复评并记录症状变化。", "reassessment_content"),
        _criterion("remeasure_vitals", "复评时重新测量关键生命体征", max_score * 0.4, max_score * 0.4 * recheck_quality, remeasured, _recheck_evidence(ctx, recheck_quality), "复评后未完整重新测量关键生命体征", "病情变化后应复测客观指标，识别趋势恶化。", "复评时至少复测 HR、BP、RR、SpO2、NRS/疼痛评分，必要时加意识与皮肤灌注。", "reassessment_content"),
        _criterion("symptom_change", "复评时询问症状变化和高危表现", max_score * 0.25, max_score * 0.25 if symptom_review else 0, symptom_review, "已有问诊/复评记录" if symptom_review else "未见症状变化复核", "未复核症状变化", "动态分诊需要把主诉变化和生命体征趋势一起判断。", "询问疼痛是否加重、头晕、冷汗、气短、意识变化等。", "reassessment_content"),
    ]


def _deterioration_upgrade_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    needs = ctx["deterioration"]
    recognized = ctx["recognized_deterioration"]
    upgraded = _is_upgrade(ctx)
    final = ctx["final_decision"] or {}
    final_level = final.get("level") or ctx["record"].get("final_level_selected")
    final_area = final.get("area") or ctx["record"].get("final_zone_selected")
    safe_upgrade = upgraded and _level_area_consistent(final_level, final_area)
    notified = _doctor_notified(ctx, timely=True)
    return [
        _criterion("recognize_deterioration", "识别候诊期间病情变化", max_score * 0.35, max_score * 0.35 if (not needs or recognized) else 0, (not needs or recognized), "已识别/处理恶化" if recognized else "未见恶化识别记录", "患者状态恶化后未被识别或复评", "病情恶化是动态病例重新分诊的核心触发条件。", "看到冷汗、头晕、血压下降、心率升高、疼痛加重时立即升级警觉。", "deterioration_upgrade"),
        _criterion("upgrade_triage", "必要时升级分诊等级并匹配区域", max_score * 0.4, max_score * 0.4 if (not needs or safe_upgrade) else max_score * 0.18 if upgraded else 0, (not needs or safe_upgrade), "已完成升级分诊且区域匹配" if safe_upgrade else "已调整等级但区域不匹配" if upgraded else "未见升级分诊", "复评后仍未升级分诊，或升级后区域与等级不匹配", "恶化后最终等级和区域都应符合病例最终标准。", "重新分诊并记录新的等级、区域和处置链路；Ⅰ级不能留在黄区或绿区。", "deterioration_upgrade"),
        _criterion("notify_after_worsening", "危重化后通知医生", max_score * 0.25, max_score * 0.25 if (not needs or notified) else 0, (not needs or notified), "已通知医生" if notified else "未见通知医生", "候诊区危重化后未通知医生", "高危或恶化患者需要及时升级处置链路。", "升级分诊时同步通知医生。", "deterioration_upgrade"),
    ]


def _communication_criteria(max_score: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    noted = "record_note" in ctx["action_types"] or bool(ctx["notes"]) or bool(ctx.get("triage_reason"))
    explained = ctx["question_count"] > 0 or bool(ctx["record"].get("messages"))
    decision_recorded = bool(ctx["triage_decisions"]) or bool(ctx["record"].get("final_level_selected"))
    return [
        _criterion("explain_waiting", "向患者解释等待/复评安排", max_score * 0.3, max_score * 0.3 if explained else 0, explained, "有对话记录" if explained else "未见沟通记录", "缺少等待或复评说明", "护理教育训练要求记录沟通和等待安全告知。", "提交前记录已告知患者症状加重及时报告。", "communication"),
        _criterion("record_note", "记录复评和重新分诊说明", max_score * 0.4, max_score * 0.4 if noted else 0, noted, "已有记录说明" if noted else "未保存记录说明", "未记录病情变化或重新分诊结果", "严重遗漏记录会影响交接和患者安全追溯。", "记录复评时间、生命体征、分诊等级变化和通知医生情况。", "communication"),
        _criterion("decision_trace", "分诊决策可追溯", max_score * 0.3, max_score * 0.3 if decision_recorded else 0, decision_recorded, "已有分诊决策记录" if decision_recorded else "未见分诊决策记录", "分诊决策缺少可追溯记录", "训练报告必须能追溯到学员操作和评分依据。", "确保初始分诊和复评分诊分别保存。", "communication"),
    ]


def _criterion(
    cid: str,
    label: str,
    max_score: float,
    score: float,
    met: bool,
    evidence: str,
    deduction_reason: str,
    standard_basis: str,
    improvement: str,
    reference_key: str,
    warning: bool = False,
) -> dict[str, Any]:
    score = round(max(0, min(score, max_score)), 2)
    max_score = round(max_score, 2)
    return {
        "id": cid,
        "label": label,
        "score": score,
        "max": max_score,
        "max_score": max_score,
        "met": bool(met),
        "status": "complete" if met and score >= max_score * 0.8 else "partial" if score > 0 else "missed",
        "warning": warning,
        "evidence": evidence,
        "deduction_reason": "" if met else deduction_reason,
        "missed_reason": "" if met else deduction_reason,
        "standard_basis": standard_basis,
        "international_reference": _international_reference(reference_key),
        "improvement": improvement if not met else "",
        "teaching_point": improvement,
    }


def _classify_dimension(name: str, index: int) -> str:
    if "第一眼" in name:
        return "first_look"
    if "病史" in name or "主诉" in name:
        return "history"
    if "生命体征" in name or "客观" in name:
        return "vitals"
    if "高危" in name or "风险" in name:
        return "risk"
    if "等级" in name:
        return "triage_level"
    if "处置" in name or "区域" in name:
        return "disposition"
    if "候诊复评" in name or "安全管理" in name:
        return "safety_management"
    if "复评时间" in name:
        return "reassessment_time"
    if "复评内容" in name or ("复评" in name and "安全" not in name and "升级" not in name):
        return "reassessment_content"
    if "变化" in name or "升级" in name or "重新分诊" in name:
        return "deterioration_upgrade"
    if "沟通" in name or "记录" in name or "解释" in name:
        return "communication"
    fallback = [
        "first_look",
        "history",
        "vitals",
        "risk",
        "triage_level",
        "disposition",
        "safety_management",
        "reassessment_content",
        "deterioration_upgrade",
        "communication",
    ]
    return fallback[index] if index < len(fallback) else "overall"


def _score_status(score: float, max_score: float) -> str:
    if score >= max_score * 0.9:
        return "complete"
    if score >= max_score * 0.7:
        return "good"
    if score > 0:
        return "partial"
    return "missed"


def _dimension_summary(name: str, score: float, max_score: float, criteria: list[dict[str, Any]]) -> str:
    missed = [c["label"] for c in criteria if c.get("deduction_reason")]
    if not missed:
        return f"{name}完成度较好，得分{score:g}/{max_score:g}。"
    return f"{name}扣{max_score - score:g}分，主要问题: " + "、".join(missed[:3])


def _dimension_basis(kind: str, ctx: dict[str, Any]) -> str:
    if kind == "triage_level":
        return f"病例标准初始等级{ctx['standard_initial_level'] or '未配置'}，最终等级{ctx['standard_final_level'] or '未配置'}；规则引擎最低等级{ctx['rule_result'].get('minimum_level_by_rules', '未计算')}。"
    if kind == "disposition":
        return f"病例标准初始区域{ctx['standard_initial_area'] or '未配置'}，最终区域{ctx['standard_final_area'] or '未配置'}。"
    if kind == "safety_management":
        return "以病例标准处置、区域安排、生命体征监测、通知医生和记录说明作为安全管理评分依据。"
    if kind in {"reassessment_time", "reassessment_content", "deterioration_upgrade"}:
        return "动态病例以时间轴事件、复评记录、重新分诊和通知医生记录作为评分依据。"
    return "以病例标准答案、学员操作记录、生命体征测量记录和规则引擎结果作为评分依据。"


def _international_reference(kind: str) -> str:
    references = {
        "first_look": "参考ESI/ATS/CTAS共同原则: 先识别复苏需求、高危状态、意识改变和明显痛苦。",
        "history": "参考ESI/CTAS/MTS分诊思路: 用主诉、症状变化、伴随症状和危险因素判断紧急程度。",
        "vitals": "参考ESI生命体征危险区和ATS/CTAS时间敏感分诊原则: 客观指标异常会提高紧急度。",
        "risk": "参考五级分诊系统患者安全目标: 优先识别胸痛、卒中、低氧、休克、意识障碍、大出血等红旗。",
        "triage_level": "参考ESI/ATS/CTAS五级分层思想: 分诊等级不能低于患者安全所需的最低紧急度。",
        "disposition": "参考急诊分诊流程: 等级、区域、通知医生和优先流程需要保持一致。",
        "safety_management": "参考急诊患者安全管理原则: 高危患者应避免普通候诊，完成监测、通知医生和可追溯记录。",
        "reassessment_time": "参考ATS/CTAS时间敏感原则: 候诊患者应按紧急度设置复评或最大等待时间。",
        "reassessment_content": "参考动态分诊实践: 病情变化后需重新评估主诉、外观和生命体征趋势。",
        "deterioration_upgrade": "参考高危患者安全管理原则: 候诊恶化后应复评、升级分诊、调整区域并通知医生。",
        "communication": "参考护理记录和交接安全要求: 关键评估、复评、升级和通知医生必须可追溯。",
    }
    return references.get(kind, "参考国际五级急诊分诊框架的紧急度、风险和资源需求原则。")


def _dimension_improvement(kind: str, criteria: list[dict[str, Any]]) -> str:
    missed = [c.get("improvement") for c in criteria if c.get("deduction_reason")]
    if missed:
        return missed[0]
    return ""


def _required_measurements(case_data: dict[str, Any]) -> list[dict[str, str]]:
    items = []
    for item in case_data.get("required_measurements") or []:
        if isinstance(item, dict):
            item_id = str(item.get("id", ""))
            if canonical_measurement(item_id) in {"other_assessments", "history_items", "focused_history", "otherassessments"}:
                continue
            items.append({"id": item_id, "label": str(item.get("label") or item.get("id") or "")})
        elif item:
            items.append({"id": str(item), "label": str(item)})
    if not items:
        for vid, label in CRITICAL_VITALS.items():
            items.append({"id": vid, "label": label})
    return [item for item in items if item["id"]]


def _red_flags(case_data: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    for value in (
        case_data.get("red_flags") or [],
        case_data.get("feedback", {}).get("key_red_flag") or [],
        case_data.get("dynamic_feedback", {}).get("key_red_flag") or [],
    ):
        if isinstance(value, list):
            flags.extend(str(v) for v in value if v)
        elif value:
            flags.append(str(value))
    for state in case_data.get("patient_states") or []:
        for signal in state.get("risk_signals") or []:
            flags.append(str(signal))
    return list(dict.fromkeys(flags))[:8]


def _missed_slot_labels(slots: list[dict[str, Any]], disclosed: set[str], limit: int) -> list[str]:
    labels = []
    for slot in slots:
        slot_id = slot.get("slot_id")
        if slot_id and slot_id not in disclosed:
            labels.append(str(slot.get("label") or slot_id))
        if len(labels) >= limit:
            break
    return labels


def _rule_hit_evidence(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "未见规则命中"
    return "；".join(f"{h.get('rule_id', 'rule')}: {h.get('evidence', '')}" for h in hits[:3])


def _canonical_vital(item_id: str) -> str:
    normalized = str(item_id or "").strip().lower()
    for canonical, aliases in VITAL_ALIASES.items():
        if normalized in aliases:
            return canonical
    return canonical_measurement(normalized)


def _canonical_vitals(items: set[str]) -> set[str]:
    return {_canonical_vital(item) for item in items if item}


def _doctor_notified(ctx: dict[str, Any], timely: bool = False) -> bool:
    deterioration_minute = _deterioration_minute(ctx) if timely else None

    def is_timely(minute: Any) -> bool:
        if deterioration_minute is None:
            return True
        try:
            return int(minute or 0) >= deterioration_minute
        except (TypeError, ValueError):
            return False

    final_disposition = ctx["record"].get("final_disposition") or []
    if bool(ctx["notification_events"]):
        if not timely or any(is_timely(item.get("simulation_minute")) for item in ctx["notification_events"]):
            return True
    if not timely and any(_has_notify_marker(item) for item in final_disposition):
        return True
    if any(decision.get("notify_doctor") and is_timely(decision.get("simulation_minute")) for decision in ctx["triage_decisions"]):
        return True
    for action in (ctx.get("actions") or []) + (ctx["record"].get("actions") or []):
        payload = action.get("payload") or {}
        minute = _action_minute(action)
        if action.get("action_type") == "notify_doctor" and is_timely(minute):
            return True
        if not timely and action.get("action_type") == "submit_disposition" and any(_has_notify_marker(item) for item in payload.get("disposition", [])):
            return True
    return False


def _has_notify_marker(value: Any) -> bool:
    text = str(value or "").lower()
    return "notify_doctor" in text or "通知医生" in text or "通知医师" in text or "医生" in text


def _has_bp_alias(measured: set[str]) -> bool:
    return bool(measured.intersection({"blood_pressure", "blood_pressure_systolic", "blood_pressure_diastolic"}))


def _has_rechecked_after_deterioration(ctx: dict[str, Any]) -> bool:
    return _recheck_quality(ctx) >= 0.8


def _deterioration_minute(ctx: dict[str, Any]) -> int | None:
    minutes = []
    for event in (ctx.get("state") or {}).get("timeline_events") or []:
        if event.get("triggered") and event_indicates_deterioration(event):
            try:
                minutes.append(int(event.get("scheduled_minute") or 0))
            except (TypeError, ValueError):
                pass
    return min(minutes) if minutes else None


def _action_minute(action: dict[str, Any]) -> int:
    detail = action.get("detail") if isinstance(action.get("detail"), dict) else {}
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    for value in (action.get("simulation_minute"), detail.get("minute"), payload.get("minute"), payload.get("simulation_minute")):
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _expected_reassessment_minutes(ctx: dict[str, Any]) -> int:
    timeline = (ctx.get("case") or {}).get("dynamic_timeline") or {}
    initial_stage = timeline.get("initial_stage") or {}
    if isinstance(initial_stage, dict):
        try:
            value = int(initial_stage.get("reassessment_due_minutes") or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    rank = _level_rank(ctx.get("standard_initial_level"))
    if rank <= 1:
        return 0
    if rank == 2:
        return 10
    if rank == 3:
        return 30
    return 60


def _required_recheck_items(ctx: dict[str, Any]) -> set[str]:
    configured = (ctx.get("state") or {}).get("reassessment_required_items") or []
    items = {_canonical_vital(item) for item in configured if item}
    if not items:
        items = {"heart_rate", "blood_pressure", "respiratory_rate", "spo2", "pain_score"}
    if ctx.get("is_dynamic_case"):
        items.update({"heart_rate", "blood_pressure", "pain_score"})
    return {item for item in items if item and item not in {"other_assessments", "history_items", "focused_history"}}


def _log_canonical_items(log: dict[str, Any]) -> set[str]:
    items = set()
    for value in log.get("canonical_items") or []:
        items.add(_canonical_vital(value))
    for value in log.get("measurement_ids") or []:
        items.add(_canonical_vital(value))
    result = log.get("result") or {}
    if isinstance(result, dict):
        for key in result.keys():
            items.add(_canonical_vital(key))
    return {item for item in items if item and item not in {"other_assessments", "history_items", "focused_history"}}


def _effective_recheck_logs(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    deterioration_minute = _deterioration_minute(ctx)
    if deterioration_minute is None:
        return []
    return [
        log for log in ctx.get("vital_log") or []
        if int(log.get("simulation_minute") or 0) >= deterioration_minute
    ]


def _recheck_quality(ctx: dict[str, Any]) -> float:
    if not ctx.get("deterioration"):
        return 1.0
    required = _required_recheck_items(ctx)
    if not required:
        return 1.0
    best = 0.0
    for log in _effective_recheck_logs(ctx):
        coverage = len(_log_canonical_items(log).intersection(required)) / max(len(required), 1)
        best = max(best, coverage)
    return round(min(best, 1.0), 4)


def _recheck_evidence(ctx: dict[str, Any], quality: float) -> str:
    if not ctx.get("deterioration"):
        return "本病例未触发恶化复测要求"
    required = _required_recheck_items(ctx)
    logs = _effective_recheck_logs(ctx)
    if not logs:
        return "恶化后未见有效复测记录"
    best_items = max((_log_canonical_items(log) for log in logs), key=lambda items: len(items.intersection(required)), default=set())
    missing = sorted(required - best_items)
    if not missing:
        return f"恶化后已复测关键项目，覆盖率{quality:.0%}"
    return f"恶化后复测覆盖率{quality:.0%}；缺少: {', '.join(missing)}"


def _level_accuracy(selected: str | None, standard: str | None, max_score: float) -> dict[str, Any]:
    if not standard:
        return {"score": max_score if selected else 0, "met": bool(selected), "warning": False, "deduction": "未记录分诊等级" if not selected else ""}
    if not selected:
        return {"score": 0, "met": False, "warning": False, "deduction": "未记录分诊等级"}
    selected_rank = _level_rank(selected)
    standard_rank = _level_rank(standard)
    if selected_rank == standard_rank:
        return {"score": max_score, "met": True, "warning": False, "deduction": ""}
    if selected_rank < standard_rank:
        return {"score": round(max_score * 0.6, 2), "met": False, "warning": True, "deduction": "分诊等级高于病例标准，应说明依据并保证区域/流程匹配"}
    return {"score": 0, "met": False, "warning": False, "deduction": "分诊等级低于病例标准或规则最低安全等级"}


def _is_red_area(area: str | None) -> bool:
    text = str(area or "")
    return any(token in text for token in ("红区", "抢救", "复苏", "急诊优先处置区"))


def _is_special_channel(area: str | None) -> bool:
    text = str(area or "")
    return "绿色通道" in text or "专病" in text or "优先" in text


def _is_green_waiting_area(area: str | None) -> bool:
    text = str(area or "")
    return "绿区" in text and "绿色通道" not in text


def _area_matches_standard(area: str | None, standard_area: str | None, selected_level: str | None = None) -> bool:
    if not standard_area:
        return bool(area)
    if str(area or "") == str(standard_area):
        return True
    if _level_rank(selected_level) == 1:
        return _is_red_area(area)
    if _is_red_area(standard_area):
        return _is_red_area(area)
    if _is_special_channel(standard_area):
        return (_is_special_channel(area) or _is_red_area(area)) and not _is_green_waiting_area(area)
    if "黄区" in str(standard_area):
        return "黄区" in str(area or "") or _is_red_area(area) or _is_special_channel(area)
    if "绿区" in str(standard_area):
        return _is_green_waiting_area(area)
    return str(standard_area) in str(area or "")


def _level_area_consistent(level: str | None, area: str | None) -> bool:
    rank = _level_rank(level)
    if rank == 1:
        return _is_red_area(area)
    if rank == 2:
        return (_is_red_area(area) or _is_special_channel(area) or "黄区" in str(area or "")) and not _is_green_waiting_area(area)
    if rank == 3:
        return "黄区" in str(area or "") or _is_special_channel(area) or _is_red_area(area)
    if rank == 4:
        return _is_green_waiting_area(area) or bool(area)
    return bool(area)


def _level_not_lower(selected: str | None, standard: str | None) -> bool:
    if not standard:
        return bool(selected)
    if not selected:
        return False
    return _level_rank(selected) <= _level_rank(standard)


def _level_rank(level: str | None) -> int:
    return LEVEL_RANK.get(str(level or ""), 5)


def _is_upgrade(ctx: dict[str, Any]) -> bool:
    init_level = (ctx["init_decision"] or {}).get("level") or ctx["state"].get("initial_level_selected")
    final_level = (ctx["final_decision"] or {}).get("level") or ctx["record"].get("final_level_selected")
    if not final_level:
        return False
    if ctx.get("standard_final_level") and _level_rank(final_level) > _level_rank(ctx["standard_final_level"]):
        return False
    if init_level and _level_rank(final_level) < _level_rank(init_level):
        return True
    return _level_not_lower(final_level, ctx["standard_final_level"]) and ctx["standard_final_level"] != ctx["standard_initial_level"]


def _as_number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
