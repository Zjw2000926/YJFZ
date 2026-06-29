"""Conversation-aware evidence extraction for expert feedback.

The triage dialogue matcher can miss a slot even when the learner asked the
right question and the patient answered naturally. This module gives feedback
generation a second evidence pass over the full conversation, measurements,
actions, and submitted notes. It does not create new medical facts; it only
decides whether an expected item is already evidenced in the record.
"""

from __future__ import annotations

import re
from typing import Any


FEEDBACK_EVIDENCE_VERSION = "conversation_evidence_v1"


SEMANTIC_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "onset_time": {
        "triggers": ("开始时间", "起病", "发作时间", "持续时间", "多久", "多长", "几分钟"),
        "evidence": ("什么时候", "多久", "多长", "开始", "发作", "起病", "刚才", "突然", "分钟", "小时", "半小时", "十来分钟", "30分钟"),
    },
    "chief_complaint_location": {
        "triggers": ("主诉", "哪里不舒服", "哪里疼", "哪儿疼", "部位", "位置"),
        "evidence": ("哪里不舒服", "哪不舒服", "哪里疼", "哪儿疼", "部位", "位置", "胸口", "胸部", "腹部", "右下腹", "头痛", "头疼", "这一块", "这里疼"),
    },
    "pain_quality": {
        "triggers": ("性质", "怎么疼", "压榨", "刺痛", "闷痛"),
        "evidence": ("性质", "怎么疼", "压榨", "压得", "像石头", "闷", "闷得慌", "刺痛", "绞痛", "烧灼", "胀痛"),
    },
    "severity": {
        "triggers": ("程度", "疼痛评分", "严重", "NRS", "评分"),
        "evidence": ("几分", "评分", "疼痛评分", "nrs", "厉害", "严重", "受不了", "很难受", "七八分", "8分", "9分", "10分"),
    },
    "radiation": {
        "triggers": ("放射", "肩背", "下颌", "上肢", "左肩", "左臂"),
        "evidence": ("放射", "肩", "左肩", "左臂", "手臂", "背", "后背", "肩背", "下颌", "脖子", "没有往", "没往"),
    },
    "accompanying": {
        "triggers": ("伴随", "大汗", "冷汗", "恶心", "呕吐", "晕厥", "气促", "气短", "呼吸困难", "濒死"),
        "evidence": ("伴随", "大汗", "冷汗", "出汗", "汗", "恶心", "想吐", "呕吐", "晕厥", "晕倒", "头晕", "气促", "气短", "喘不上气", "呼吸困难", "濒死", "特别难受"),
    },
    "history_risk": {
        "triggers": ("既往", "病史", "冠心病", "高血压", "糖尿病", "吸烟", "危险因素", "基础病"),
        "evidence": ("既往", "病史", "冠心病", "心脏病", "心梗", "高血压", "糖尿病", "高脂血症", "血脂", "吸烟", "抽烟", "烟", "饮酒", "基础病"),
    },
    "medication": {
        "triggers": ("用药", "吃药", "服药", "药物", "降压药", "降糖药"),
        "evidence": ("用药", "吃药", "服药", "药", "降压药", "降糖药", "阿司匹林", "硝酸甘油", "最近稳定", "控制"),
    },
    "allergy": {
        "triggers": ("过敏", "药物过敏"),
        "evidence": ("过敏", "药物过敏", "没发现过敏", "没有过敏"),
    },
    "similar_episode": {
        "triggers": ("类似", "以前", "既往发作", "发作过", "这种情况"),
        "evidence": ("类似", "以前", "之前", "从前", "发作过", "这种情况", "同样", "有过", "没有过"),
    },
    "symptom_change": {
        "triggers": ("变化", "加重", "缓解", "趋势", "诱因", "进展", "高危相关背景"),
        "evidence": ("变化", "加重", "缓解", "越来越", "突然", "诱因", "原因", "最近", "稳定", "控制", "按时", "之前", "现在才来"),
    },
    "low_bp_shock": {
        "triggers": ("低血压", "血压下降", "休克", "灌注差", "皮肤湿冷", "血压低"),
        "evidence": ("低血压", "血压低", "血压下降", "休克", "灌注差", "皮肤湿冷", "湿冷", "82/54", "96/60", "头晕", "冷汗"),
    },
    "spo2_hypoxia": {
        "triggers": ("spo2", "SpO₂", "血氧", "氧饱和", "低氧"),
        "evidence": ("spo2", "sp02", "血氧", "氧饱和", "低氧", "92%", "下降"),
    },
}


INTENT_GROUPS = {
    "ask_onset_time": "onset_time",
    "ask_duration": "onset_time",
    "ask_chief_complaint": "chief_complaint_location",
    "ask_pain_location": "chief_complaint_location",
    "ask_pain_nature": "pain_quality",
    "ask_pain_quality": "pain_quality",
    "ask_pain_character": "pain_quality",
    "ask_severity": "severity",
    "ask_pain_score": "severity",
    "ask_pain_radiation": "radiation",
    "ask_aggravating_relieving": "symptom_change",
    "ask_breathing": "accompanying",
    "ask_dyspnea": "accompanying",
    "ask_accompanying": "accompanying",
    "ask_accompanying_symptoms": "accompanying",
    "ask_nausea_vomiting": "accompanying",
    "ask_sweating": "accompanying",
    "ask_syncope": "accompanying",
    "ask_consciousness": "accompanying",
    "ask_past_history": "history_risk",
    "ask_medical_history": "history_risk",
    "ask_cardiovascular_history": "history_risk",
    "ask_hypertension_diabetes": "history_risk",
    "ask_smoking_alcohol": "history_risk",
    "ask_medication": "medication",
    "ask_allergy": "allergy",
    "ask_similar_episode": "similar_episode",
    "ask_symptom_change": "symptom_change",
    "ask_trigger": "symptom_change",
    "ask_reason_for_visit": "symptom_change",
}


VITAL_ALIASES = {
    "temperature": {"temperature", "temperature_c", "temp", "t", "体温"},
    "heart_rate": {"heart_rate", "heart_rate_bpm", "hr", "pulse", "心率", "脉搏"},
    "respiratory_rate": {"respiratory_rate", "respiratory_rate_bpm", "rr", "respiration", "呼吸", "呼吸频率"},
    "blood_pressure": {"blood_pressure", "bp", "blood_pressure_systolic", "blood_pressure_diastolic", "systolic", "diastolic", "血压"},
    "spo2": {"spo2", "spo2_percent", "oxygen_saturation", "oxygen", "血氧", "氧饱和度", "SpO₂".lower()},
    "pain_score": {"pain_score", "nrs", "nrs_score", "pain", "疼痛评分"},
    "consciousness": {"consciousness", "mental_status", "gcs", "gcs_score", "意识"},
    "blood_glucose": {"blood_glucose", "blood_glucose_mmol_l", "glucose", "血糖"},
}

NON_VITAL_MEASUREMENT_IDS = {"other_assessments", "history_items", "focused_history", "otherassessments"}


PUNCT_RE = re.compile(r"[\s,，。；;、:：/\\|（）()【】\[\]{}\"'“”‘’]+")


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    return text.replace("％", "%").replace("₂", "2").replace("sp0", "spo")


def compact_text(value: Any) -> str:
    return PUNCT_RE.sub("", normalize_text(value))


def _contains_any(haystack: str, terms: tuple[str, ...] | list[str] | set[str]) -> bool:
    compact = compact_text(haystack)
    for term in terms:
        t = compact_text(term)
        if t and t in compact:
            return True
    return False


def _append_text(parts: list[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for item in value.values():
            _append_text(parts, item)
        return
    if isinstance(value, list):
        for item in value:
            _append_text(parts, item)
        return
    parts.append(str(value))


def collect_record_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for message in record.get("messages") or []:
        if message.get("role") in {"student", "user", "nurse"}:
            _append_text(parts, message.get("content"))
    for action in record.get("student_actions") or []:
        _append_text(parts, action.get("detail"))
        _append_text(parts, action.get("feedback"))
    for key in (
        "triage_reason",
        "triage_note",
        "note",
        "notes",
        "final_disposition",
        "notification_events",
        "observed_items",
    ):
        _append_text(parts, record.get(key))
    return "\n".join(parts)


def _slot_text(slot: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("slot_id", "id", "label", "keywords", "canonical_intents", "answer_facts", "answer"):
        _append_text(parts, slot.get(key))
    return " ".join(parts)


def _groups_for_text(text: str, intents: list[str] | None = None) -> set[str]:
    groups: set[str] = set()
    for group_name, spec in SEMANTIC_GROUPS.items():
        if _contains_any(text, spec["triggers"]):
            groups.add(group_name)
    for intent in intents or []:
        group = INTENT_GROUPS.get(str(intent))
        if group:
            groups.add(group)
    return groups


def _terms_from_text(text: str) -> list[str]:
    terms: list[str] = []
    for chunk in PUNCT_RE.split(str(text or "")):
        chunk = chunk.strip()
        if len(compact_text(chunk)) >= 2 and chunk not in {"根据病例资料回答", "普通成人", "病例资料"}:
            terms.append(chunk)
    return terms


def _intent_events(record: dict[str, Any]) -> set[str]:
    return {str(item.get("intent")) for item in record.get("intent_events") or [] if item.get("intent")}


def is_slot_covered(slot: dict[str, Any], record: dict[str, Any], disclosed_slots: set[str] | None = None) -> bool:
    slot_id = str(slot.get("slot_id") or slot.get("id") or "")
    if disclosed_slots and slot_id in disclosed_slots:
        return True

    canonical_intents = [str(i) for i in slot.get("canonical_intents") or []]
    haystack = collect_record_text(record)
    slot_text = _slot_text(slot)
    slot_groups = _groups_for_text(slot_text, [])
    intent_groups = {INTENT_GROUPS.get(intent) for intent in canonical_intents if INTENT_GROUPS.get(intent)}
    if canonical_intents and _intent_events(record).intersection(canonical_intents):
        # A raw intent match is only enough when it fits the slot's semantic
        # category. This prevents bad case metadata, such as a similar-episode
        # slot tagged as ask_onset_time, from awarding unrelated credit.
        if not slot_groups or slot_groups.intersection(intent_groups):
            return True

    for group in (slot_groups | intent_groups):
        if _contains_any(haystack, SEMANTIC_GROUPS[group]["evidence"]):
            return True

    terms = _terms_from_text(slot_text)
    if terms and _contains_any(haystack, terms):
        return True
    return False


def canonical_measurement(value: Any) -> str:
    compact = compact_text(value)
    for canonical, aliases in VITAL_ALIASES.items():
        if compact in {compact_text(alias) for alias in aliases}:
            return canonical
        if any(compact_text(alias) and compact_text(alias) in compact for alias in aliases):
            return canonical
    return compact


def _is_non_vital_measurement(value: Any) -> bool:
    return canonical_measurement(value) in NON_VITAL_MEASUREMENT_IDS


def collect_measured_items(record: dict[str, Any], measured: list[Any] | None = None) -> set[str]:
    items = {canonical_measurement(item) for item in (measured or record.get("measured_vitals") or []) if item}
    for action in record.get("student_actions") or []:
        detail = action.get("detail") or {}
        payload = action.get("action_payload") or {}
        for key in ("measurement_ids", "measurements", "items", "result"):
            value = detail.get(key) if isinstance(detail, dict) else None
            _collect_measurement_value(items, value)
            value = payload.get(key) if isinstance(payload, dict) else None
            _collect_measurement_value(items, value)
    for log in record.get("vital_measurement_log") or []:
        _collect_measurement_value(items, log.get("result"))
        _collect_measurement_value(items, log.get("items"))
    return {item for item in items if item and item not in NON_VITAL_MEASUREMENT_IDS}


def _collect_measurement_value(items: set[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for key in value.keys():
            if not _is_non_vital_measurement(key):
                items.add(canonical_measurement(key))
        return
    if isinstance(value, list):
        for item in value:
            _collect_measurement_value(items, item)
        return
    if not _is_non_vital_measurement(value):
        items.add(canonical_measurement(value))


def filter_missed_slots(case_data: dict[str, Any], record: dict[str, Any], disclosed: list[str] | None = None) -> list[str]:
    disclosed_set = {str(item) for item in (disclosed or record.get("disclosed_slots") or [])}
    slots = case_data.get("dialogue_state_machine", {}).get("slots", []) or []
    missed = []
    for slot in slots:
        if slot.get("is_required", True) is False:
            continue
        if not is_slot_covered(slot, record, disclosed_set):
            missed.append(slot.get("label") or slot.get("slot_id") or str(slot))
    return _unique(missed)


def detect_record_groups(record: dict[str, Any]) -> set[str]:
    haystack = collect_record_text(record)
    groups = {
        group_name
        for group_name, spec in SEMANTIC_GROUPS.items()
        if _contains_any(haystack, spec["evidence"])
    }
    for intent in _intent_events(record):
        group = INTENT_GROUPS.get(intent)
        if group:
            groups.add(group)
    return groups


def covered_slot_groups(case_data: dict[str, Any], record: dict[str, Any], disclosed: list[str] | None = None) -> dict[str, list[str]]:
    disclosed_set = {str(item) for item in (disclosed or record.get("disclosed_slots") or [])}
    grouped: dict[str, list[str]] = {}
    for slot in case_data.get("dialogue_state_machine", {}).get("slots", []) or []:
        if slot.get("is_required", True) is False or not is_slot_covered(slot, record, disclosed_set):
            continue
        slot_groups = _groups_for_text(_slot_text(slot), [str(i) for i in slot.get("canonical_intents") or []])
        for group in slot_groups:
            grouped.setdefault(group, []).append(str(slot.get("label") or slot.get("slot_id") or group))
    return {group: _unique(labels) for group, labels in grouped.items()}


def filter_missed_measurements(required_measurements: list[dict[str, Any]], record: dict[str, Any], measured: list[Any] | None = None) -> list[str]:
    measured_items = collect_measured_items(record, measured)
    missed = []
    for item in required_measurements or []:
        raw_id = item.get("id") or item.get("measurement_id") or item.get("key") or item.get("label")
        canonical = canonical_measurement(raw_id)
        if canonical in NON_VITAL_MEASUREMENT_IDS:
            continue
        if canonical not in measured_items:
            missed.append(item.get("label") or raw_id)
    return _unique(missed)


def _split_red_flag(flag: Any) -> list[str]:
    parts = [p.strip() for p in re.split(r"[；;]", str(flag or "")) if p.strip()]
    if len(parts) > 1:
        return parts
    return [str(flag)] if flag else []


def _red_flag_piece_covered(piece: str, record: dict[str, Any], measured_items: set[str]) -> bool:
    haystack = collect_record_text(record)
    piece_text = normalize_text(piece)
    if _contains_any(haystack, _terms_from_text(piece_text)):
        return True
    for group in _groups_for_text(piece_text):
        if _contains_any(haystack, SEMANTIC_GROUPS[group]["evidence"]):
            return True
    if _contains_any(piece_text, SEMANTIC_GROUPS["spo2_hypoxia"]["triggers"]) and "spo2" in measured_items:
        return True
    if _contains_any(piece_text, SEMANTIC_GROUPS["low_bp_shock"]["triggers"]) and "blood_pressure" in measured_items:
        return True
    if _contains_any(piece_text, ("心率", "hr", "脉搏")) and "heart_rate" in measured_items:
        return True
    return False


def filter_missed_red_flags(red_flags: list[Any], record: dict[str, Any], measured: list[Any] | None = None) -> list[str]:
    measured_items = collect_measured_items(record, measured)
    missed = []
    for flag in red_flags or []:
        pieces = _split_red_flag(flag)
        uncovered = [piece for piece in pieces if not _red_flag_piece_covered(piece, record, measured_items)]
        if len(pieces) > 1:
            missed.extend(uncovered)
        elif uncovered:
            missed.append(str(flag))
    return _unique(missed)


def build_feedback_evidence(case_data: dict[str, Any], record: dict[str, Any], disclosed: list[str] | None = None, measured: list[Any] | None = None) -> dict[str, Any]:
    disclosed_set = {str(item) for item in (disclosed or record.get("disclosed_slots") or [])}
    slots = case_data.get("dialogue_state_machine", {}).get("slots", []) or []
    covered_slots = [
        slot.get("label") or slot.get("slot_id")
        for slot in slots
        if slot.get("is_required", True) is not False and is_slot_covered(slot, record, disclosed_set)
    ]
    measured_items = sorted(collect_measured_items(record, measured))
    red_flags = case_data.get("red_flags") or []
    covered_red_flags = []
    for flag in red_flags:
        pieces = _split_red_flag(flag)
        covered_red_flags.extend([piece for piece in pieces if _red_flag_piece_covered(piece, record, set(measured_items))])

    covered_items = _unique([*covered_slots, *covered_red_flags])
    return {
        "version": FEEDBACK_EVIDENCE_VERSION,
        "basis": "专家反馈综合已命中的问诊槽位、对话全文、生命体征测量、操作记录和提交说明生成。",
        "covered_question_items": _unique(covered_slots)[:12],
        "covered_red_flags": _unique(covered_red_flags)[:12],
        "measured_items": measured_items,
        "covered_items": covered_items[:16],
    }


def _unique(items: list[Any]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = compact_text(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
