"""统一虚拟患者回答服务 — 拟人化对话整改

职责:
1. 意图识别
2. slot 匹配（支持多slot合并，最多2个）
3. 操作类回应
4. LLM 自然化
5. 分层 fallback（操作→模糊匹配→语义→LLM兜底→角色化不知道）
6. 安全过滤
7. 事件记录
"""

import os, re, random
from typing import Optional
from services.triage_intent import match_intent, get_intent_slot_mapping
from services.triage_guard import sanitize_triage_reply
from services.llm_service import call_llm

# ── 操作类回应 ──
OPERATION_REPLIES = [
    "嗯，你量吧。",
    "好，您快点，我有点难受。",
    "可以，我配合。",
    "行，我现在还是不舒服，你先测吧。",
    "好的，我尽量配合。",
    "嗯…现在就测吗？",
    "好，您测吧，我就是有点紧张。",
]

# ── 角色化不知道（不破坏沉浸感）──
ROLE_FALLBACKS = {
    "medication": [
        "药名我记不太清了，您可以再问具体一点，我尽量想想。",
        "这个我一下说不准，平时有没有固定吃药我得再确认一下。",
        "具体药物我记不清，不能乱说。",
    ],
    "time_detail": [
        "我说不太清楚具体几点开始的，大概就是刚才那一阵。",
        "差不多就刚才吧，具体什么时间我记不太清。",
    ],
    "history": [
        "这个我记不太清，不能乱说。",
        "以前有没有明确诊断我不确定，得再核实一下。",
    ],
    "general": [
        "这个我确实不太清楚，就是现在这点不舒服让我有点担心。",
        "我说不好，就是人很不对劲。",
        "这个我不太懂，您看我这个情况严重吗？",
    ],
}

QUESTION_TYPES = {
    "factual_question",
    "subjective_question",
    "trigger_question",
    "diagnostic_question",
    "out_of_scope_question",
}


def classifyQuestionType(userInput: str) -> str:
    """Classify the nurse's question before choosing an answer policy.

    Facts stay grounded in the case. The classification only decides whether
    unknown information may be answered with natural patient uncertainty.
    """
    text = str(userInput or "").strip()
    if not text:
        return "out_of_scope_question"

    trigger_terms = [
        "什么原因", "什么引起", "什么导致", "为什么", "诱因", "原因",
        "吃坏", "吃东西", "吃完", "饭后", "有没有什么引起", "怎么引起",
        "撞击", "撞到", "碰撞", "碰到", "撞伤", "搬东西", "搬重物", "扭伤", "扭到", "外伤",
    ]
    if any(term in text for term in trigger_terms):
        return "trigger_question"

    diagnostic_terms = [
        "是不是", "会不会是", "是不是得了", "是不是患了", "能不能诊断",
        "阑尾炎", "心梗", "心肌梗死", "胃穿孔", "宫外孕", "异位妊娠",
        "脑卒中", "中风", "休克", "败血症", "诊断",
    ]
    if any(term in text for term in diagnostic_terms):
        return "diagnostic_question"

    subjective_terms = [
        "怎么疼", "什么感觉", "感觉怎么样", "厉害吗", "难受吗", "舒服点",
        "变化", "加重", "减轻", "现在怎么样", "疼得怎么样",
    ]
    if any(term in text for term in subjective_terms):
        return "subjective_question"

    factual_terms = [
        "什么时候", "多久", "多长时间", "几点", "开始", "哪里", "哪个位置",
        "部位", "几分", "多少分", "有没有", "是否", "以前", "过去",
        "病史", "过敏", "吃药", "用药", "月经", "怀孕", "阴道流血",
    ]
    if any(term in text for term in factual_terms):
        return "factual_question"

    return "out_of_scope_question"


def _answer_policy(question_type: str) -> dict:
    return {
        "question_type": question_type,
        "allow_natural_uncertainty": question_type in {
            "subjective_question", "trigger_question", "out_of_scope_question"
        },
        "must_not_diagnose": question_type == "diagnostic_question",
        "prefer_trigger_answer": question_type == "trigger_question",
    }


def _is_operation_input(text):
    """判断是否为操作类输入"""
    if classifyQuestionType(text) in {"trigger_question", "diagnostic_question", "subjective_question"}:
        return False
    kw = ["测","量","检查","看一下","听一下","测一下","我来","给你测","给你量",
          "测生命体征","量血压","测血氧","测体温","测心率","测血糖"]
    return any(k in text for k in kw)

def _get_role_fallback(category="general"):
    pool = ROLE_FALLBACKS.get(category, ROLE_FALLBACKS["general"])
    return random.choice(pool)

def _fuzzy_match_slot(query, slots):
    """slot label 模糊匹配"""
    best = None
    best_score = 0
    for s in slots:
        label = s.get("label","")
        score = sum(1 for c in query if c in label) / max(len(query), 1)
        if score > 0.4 and score > best_score:
            best = s
            best_score = score
    return best

def _clean_fact(fact):
    return str(fact or "").strip()


def _first_fact(slot):
    for fact in slot.get("answer_facts", []) or []:
        cleaned = _clean_fact(fact)
        if cleaned:
            return cleaned
    return ""


def _is_placeholder_fact(fact):
    cleaned = _clean_fact(fact)
    return not cleaned or cleaned in {
        "根据病例资料回答。",
        "根据病例资料回答",
        "根据病例资料回答该项内容。",
        "根据病例资料回答该项内容",
    }


def _is_non_informative_fact(fact):
    cleaned = _clean_fact(fact)
    return _is_placeholder_fact(cleaned) or cleaned in {"儿童", "老年人", "成人", "育龄女性", "孕产妇"}


def _case_initial_texts(case_data):
    initial = case_data.get("initial_exposure", {}) or {}
    return {
        _clean_fact(initial.get("chief_complaint")),
        _clean_fact(initial.get("opening_line")),
    } - {""}


def _is_generic_initial_fact(fact, case_data):
    return _clean_fact(fact) in _case_initial_texts(case_data)


def _slot_quality(slot, case_data):
    """给同一 intent 下的候选 slot 排序，优先选病例内更具体的事实。"""
    fact = _first_fact(slot)
    score = 0
    if not _is_placeholder_fact(fact):
        score += 20
    if fact and not _is_generic_initial_fact(fact, case_data):
        score += 15
    if not str(slot.get("slot_id", "")).startswith("slot_"):
        score += 8
    if slot.get("is_required"):
        score += 2
    if slot.get("label"):
        score += 1
    return score


def _select_best_slot(intent_id, all_slots, disclosed, case_data):
    candidates = [
        slot for slot in all_slots
        if intent_id in slot.get("canonical_intents", [])
        and slot.get("slot_id") not in disclosed
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda slot: _slot_quality(slot, case_data))


def _unique_list(items):
    result = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _append_disclosed(disclosed, slot_ids):
    for sid in slot_ids:
        if sid and sid not in disclosed:
            disclosed.append(sid)
    return disclosed


def _normalize_reply_text(reply):
    reply = re.sub(r"。{2,}", "。", reply or "")
    reply = reply.replace("。，", "，").replace("。；", "；")
    reply = reply.replace("。”。", "。”")
    return reply.strip()


def _naturalize_fact_text(fact):
    text = _strip_sentence_end(_humanize_case_text(fact))
    text = text.strip("“”\"'")
    return text


def _is_negative_fact(text):
    return any(term in text for term in ("没有", "无", "否认", "不明显", "未见"))


def _question_has_any(text, terms):
    return any(term in str(text or "") for term in terms)


def _patientize_facts(facts, question="", case_data=None, record=None):
    cleaned = []
    seen = set()
    for fact in facts:
        text = _naturalize_fact_text(fact)
        if not text:
            continue
        key = re.sub(r"\s+", "", text)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)

    if not cleaned:
        return _subjective_reply(case_data or {}, record)

    q = str(question or "")
    first = cleaned[0]
    second = cleaned[1] if len(cleaned) > 1 else ""
    joined = "，".join(cleaned[:2])

    if _question_has_any(q, ("撞击", "撞到", "碰撞", "碰到", "撞伤", "外伤")) and "搬" in joined:
        return _normalize_reply_text(f"不是被东西撞到，我记得是{joined}。")

    if _question_has_any(q, ("搬东西", "搬重物", "搬箱子", "扭伤", "扭到")) and "搬" in joined:
        return _normalize_reply_text(f"对，就是{joined}。")

    if _question_has_any(q, ("有没有", "有无", "是否", "是吗", "的吗", "吗")):
        if _is_negative_fact(joined):
            return _normalize_reply_text(f"没有，我目前能说清的就是{joined}。")
        return _normalize_reply_text(f"嗯，有的，{joined}。")

    if _question_has_any(q, ("什么时候", "多久", "多长时间", "几点", "开始", "起病")):
        return _normalize_reply_text(f"大概就是{first}，具体时间我也只能按感觉说个大概。")

    if _question_has_any(q, ("哪里", "哪个位置", "部位", "位置", "哪儿")):
        return _normalize_reply_text(f"主要就是{first}，我自己感觉这个地方最明显。")

    if _question_has_any(q, ("几分", "多少分", "厉害", "严重", "难受")):
        return _normalize_reply_text(f"现在感觉{joined}，挺不舒服的。")

    if second:
        return _normalize_reply_text(f"我现在主要就是{first}，另外{second}。")
    return _normalize_reply_text(f"我现在主要就是{first}，有点不舒服，也有点担心。")


def _current_patient_state(case_data, record=None):
    """Return the current dynamic patient state, falling back to T0/current case text."""
    record = record or {}
    timeline_state = record.get("timeline_state") or {}
    current_id = timeline_state.get("current_patient_state_id")
    current_minute = timeline_state.get("current_simulated_minute", 0)
    states = case_data.get("patient_states") or []
    if current_id:
        for state in states:
            if state.get("state_id") == current_id:
                return state
    best = None
    for state in sorted(states, key=lambda item: item.get("time_minute", 0)):
        if state.get("time_minute", 0) <= current_minute:
            best = state
    return best or {}


def _humanize_case_text(text):
    """Remove authoring phrases that sound like a rubric rather than a patient."""
    text = _clean_fact(text)
    if not text:
        return ""
    replacements = [
        ("患者说不清；女儿代述", "家属说"),
        ("患者说不清;女儿代述", "家属说"),
        ("患者说不清楚；女儿代述", "家属说"),
        ("患儿不能完整表达；母亲说", "妈妈说"),
        ("患儿不能完整表达;母亲说", "妈妈说"),
        ("患儿不能完整表达", "孩子现在说不太清"),
        ("患者说不清", "我现在说不太清"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(r"^(儿童|老年人|育龄女性|成人)\s*[，,。；;：:]*\s*", "", text)
    return text.replace("。。", "。").replace("，，", "，").strip()


def _patient_context_phrase(case_data, record=None):
    state = _current_patient_state(case_data, record)
    candidates = [
        state.get("symptom_description"),
        state.get("chief_complaint"),
        state.get("appearance"),
        (case_data.get("initial_exposure") or {}).get("chief_complaint"),
        (case_data.get("initial_exposure") or {}).get("opening_line"),
    ]
    for candidate in candidates:
        cleaned = _humanize_case_text(candidate)
        if cleaned:
            return _strip_sentence_end(cleaned)
    return "不太舒服"


def _subjective_reply(case_data, record=None):
    state = _current_patient_state(case_data, record)
    appearance = _humanize_case_text(state.get("appearance"))
    symptom = _humanize_case_text(state.get("symptom_description") or state.get("chief_complaint"))
    pain_score = state.get("pain_score")
    risk_signals = state.get("risk_signals") or []

    fragments = []
    if symptom:
        fragments.append(_strip_sentence_end(symptom))
    if appearance and appearance not in symptom:
        fragments.append(_strip_sentence_end(appearance))
    if pain_score not in (None, ""):
        fragments.append(f"疼痛大概有{pain_score}分")
    if risk_signals:
        fragments.append(_strip_sentence_end("，".join(str(item) for item in risk_signals[:2])))

    if not fragments:
        context = _patient_context_phrase(case_data, record)
        return f"我现在主要就是{context}，有点担心，想让你们帮我看看。"
    return "我现在" + "，".join(fragments[:3]) + "，有点难受，也有点担心。"


def _asks_current_state_detail(text):
    text = str(text or "")
    anchors = ("现在", "目前", "刚才", "还", "还能", "此刻", "这会儿")
    state_terms = (
        "头晕", "坐不住", "坐得住", "冷汗", "出汗", "面色", "苍白", "意识", "清醒",
        "嗜睡", "说话", "听懂", "抬手", "抽搐", "呕吐", "发绀", "呼吸", "GCS",
        "疼得", "难受", "加重", "变严重", "恶化",
    )
    return any(anchor in text for anchor in anchors) and any(term in text for term in state_terms)


def _current_state_targeted_reply(case_data, record=None):
    state = _current_patient_state(case_data, record)
    if not state:
        return _subjective_reply(case_data, record)

    symptom = _humanize_case_text(state.get("symptom_description") or state.get("chief_complaint"))
    appearance = _humanize_case_text(state.get("appearance"))
    mental = _humanize_case_text(state.get("mental_status") or state.get("consciousness"))
    risk_signals = [_humanize_case_text(item) for item in (state.get("risk_signals") or []) if item]
    pain_score = state.get("pain_score")

    fragments = []
    for item in (symptom, appearance, mental):
        cleaned = _strip_sentence_end(item)
        if cleaned and cleaned not in fragments:
            fragments.append(cleaned)
    for item in risk_signals[:2]:
        cleaned = _strip_sentence_end(item)
        if cleaned and cleaned not in fragments:
            fragments.append(cleaned)
    if pain_score not in (None, ""):
        fragments.append(f"疼痛大概{pain_score}分")

    if not fragments:
        return _subjective_reply(case_data, record)
    return _normalize_reply_text("我现在" + "，".join(fragments[:4]) + "，有点难受，也有点担心。")


def _finalize_reply(reply, case_data, record=None, question_type=""):
    """Last-mile cleanup: keep facts grounded while removing mechanical system prose."""
    cleaned = _humanize_case_text(reply)
    mechanical_terms = ("病例信息中", "系统未提供", "无法回答", "您还是问医生吧", "还是问医生吧", "我说不太准", "问得具体一点")
    if any(term in cleaned for term in mechanical_terms):
        current_message = (record or {}).get("_current_student_message", "")
        if _asks_current_state_detail(current_message):
            return _current_state_targeted_reply(case_data, record)
        if question_type == "subjective_question":
            return _subjective_reply(case_data, record)
        if question_type != "diagnostic_question":
            context = _patient_context_phrase(case_data, record)
            return _normalize_reply_text(f"这个我一下说不太准，我现在主要就是{context}，有点担心。")
    if question_type != "diagnostic_question":
        cleaned = cleaned.replace("您还是问医生吧。", "").replace("还是问医生吧。", "")
    return _normalize_reply_text(cleaned)


def _strip_sentence_end(text):
    return re.sub(r"[。！？.!?；;，,、\s]+$", "", _clean_fact(text))


def _combine_slot_facts(slots, question="", case_data=None, record=None):
    """把命中的病例事实合成患者回答；不使用占位事实，不重复同一句。"""
    facts = []
    seen = set()
    for slot in slots[:2]:
        fact = _first_fact(slot)
        if _is_non_informative_fact(fact):
            continue
        key = re.sub(r"\s+", "", fact)
        if key in seen:
            continue
        seen.add(key)
        facts.append(fact)
    if not facts:
        return "这个我说不太清楚。"
    return _patientize_facts(facts, question, case_data, record)
    sentences = []
    for fact in facts:
        if fact.endswith(("。", "！", "？", "…", ".", "!", "?")):
            sentences.append(fact)
        else:
            sentences.append(f"{fact}。")
    return _normalize_reply_text("".join(sentences))


def _all_text_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _all_text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_text_values(item)


def _find_trigger_fact(case_data):
    """Find an explicit trigger/inducement fact without inventing one."""
    state_machine = case_data.get("dialogue_state_machine", {}) or {}
    slots = state_machine.get("slots", []) or []
    trigger_slot_words = (
        "诱因", "原因", "饭后", "进食", "吃东西", "运动", "搬重物",
        "接触", "油腻", "外伤", "诱发"
    )
    negative_words = ("无明显诱因", "没有明显诱因", "无诱因", "未见明显诱因")

    for slot in slots:
        searchable = " ".join([
            str(slot.get("slot_id", "")),
            str(slot.get("label", "")),
            " ".join(slot.get("canonical_intents", []) or []),
            " ".join(slot.get("keywords", []) or []),
        ])
        facts = [_clean_fact(f) for f in slot.get("answer_facts", []) or [] if _clean_fact(f) and not _is_non_informative_fact(f)]
        if not facts:
            continue
        combined = searchable + " " + " ".join(facts)
        if any(word in combined for word in negative_words):
            return facts[0]
        if any(word in searchable for word in trigger_slot_words):
            return facts[0]

    for text in _all_text_values(case_data):
        cleaned = _clean_fact(text)
        if not cleaned or len(cleaned) > 120:
            continue
        if any(word in cleaned for word in negative_words):
            return cleaned
        if "诱因" in cleaned and any(word in cleaned for word in trigger_slot_words):
            return cleaned
    return ""


def _get_onset_hint(case_data, disclosed=None):
    disclosed = set(disclosed or [])
    state_machine = case_data.get("dialogue_state_machine", {}) or {}
    for slot in state_machine.get("slots", []) or []:
        sid = slot.get("slot_id")
        if sid in disclosed:
            continue
        searchable = " ".join([
            str(sid or ""),
            str(slot.get("label", "")),
            " ".join(slot.get("canonical_intents", []) or []),
        ])
        if any(word in searchable for word in ["onset", "起病", "开始", "时间"]):
            fact = _first_fact(slot)
            if fact and not _is_placeholder_fact(fact):
                return fact
    initial = case_data.get("initial_exposure", {}) or {}
    return _clean_fact(initial.get("chief_complaint")) or _clean_fact(initial.get("opening_line"))


def _natural_trigger_reply(case_data, disclosed=None, question=""):
    if any(word in str(question or "") for word in ["为什么现在才来", "为什么才来", "现在才来医院", "才来医院"]):
        onset = _get_onset_hint(case_data, disclosed)
        if onset:
            return _normalize_reply_text(f"一开始我想着先忍一忍，后来越来越不舒服才赶紧来医院。{onset}")
        return "一开始我想着先忍一忍，后来越来越不舒服才赶紧来医院。"

    fact = _find_trigger_fact(case_data)
    if fact:
        if any(word in fact for word in ["无明显诱因", "没有明显诱因", "无诱因", "未见明显诱因"]):
            return "我也不知道什么原因，就是突然开始不舒服的，好像没有特别明显的诱因。"
        return f"{fact} 具体是不是这个引起的，我也不确定。"

    onset = _get_onset_hint(case_data, disclosed)
    if onset:
        return _normalize_reply_text(f"我也说不清楚是什么原因，只知道{_strip_sentence_end(onset)}，之前没有特别注意到什么明显诱因。")
    return "我也说不清楚是什么原因，好像没有特别明显的诱因。"


def _is_mechanical_trigger_question(question):
    text = str(question or "")
    terms = ("撞击", "撞到", "碰撞", "碰到", "撞伤", "外伤", "搬东西", "搬重物", "扭伤", "扭到")
    return any(term in text for term in terms)


def _mechanical_trigger_reply(case_data, question):
    text = str(question or "")
    fact = _find_trigger_fact(case_data) or _get_onset_hint(case_data)
    fact_text = _strip_sentence_end(_humanize_case_text(fact))
    if not fact_text:
        return "我不太确定具体诱因，只知道当时开始不舒服了。"

    collision_terms = ("撞击", "撞到", "碰撞", "碰到", "撞伤", "外伤")
    lifting_terms = ("搬东西", "搬重物", "搬箱子", "搬")
    fact_has_lifting = any(term in fact_text for term in lifting_terms)
    fact_has_collision = any(term in fact_text for term in collision_terms)

    if any(term in text for term in collision_terms) and fact_has_lifting and not fact_has_collision:
        return _normalize_reply_text(f"不是被东西撞到，我记得是{fact_text}。")
    if any(term in text for term in lifting_terms) and fact_has_lifting:
        return _normalize_reply_text(f"对，是{fact_text}。")
    return _normalize_reply_text(f"我记得主要是{fact_text}。")


def _slots_by_ids(case_data, slot_ids):
    all_slots = (case_data.get("dialogue_state_machine") or {}).get("slots", []) or []
    by_id = {slot.get("slot_id"): slot for slot in all_slots}
    return [by_id[sid] for sid in (slot_ids or []) if sid in by_id]


def _facts_for_slots(case_data, slot_ids):
    slots = _slots_by_ids(case_data, slot_ids or [])
    facts = []
    seen = set()
    for slot in slots:
        label = slot.get("label") or slot.get("slot_id") or "病例事实"
        for fact in slot.get("answer_facts", []) or []:
            text = _naturalize_fact_text(fact)
            if not text or _is_non_informative_fact(text):
                continue
            key = re.sub(r"\s+", "", f"{label}:{text}")
            if key in seen:
                continue
            seen.add(key)
            facts.append(f"{label}: {text}")
    return facts


def _current_state_facts(case_data, record=None):
    state = _current_patient_state(case_data, record)
    initial = case_data.get("initial_exposure") or {}
    candidates = [
        ("当前主诉", state.get("chief_complaint")),
        ("当前症状", state.get("symptom_description")),
        ("当前外观", state.get("appearance")),
        ("意识状态", state.get("mental_status") or state.get("consciousness")),
        ("初始主诉", initial.get("chief_complaint") or initial.get("opening_line")),
    ]
    facts = []
    seen = set()
    for label, value in candidates:
        text = _naturalize_fact_text(value)
        if not text:
            continue
        key = re.sub(r"\s+", "", f"{label}:{text}")
        if key in seen:
            continue
        seen.add(key)
        facts.append(f"{label}: {text}")
    for signal in (state.get("risk_signals") or [])[:3]:
        text = _naturalize_fact_text(signal)
        if text:
            facts.append(f"当前风险表现: {text}")
    if state.get("pain_score") not in (None, ""):
        facts.append(f"疼痛评分: {state.get('pain_score')}")
    return facts


def _allowed_fact_pack(case_data, record, dialog_result):
    facts = _facts_for_slots(case_data, dialog_result.get("matched_slots") or [])
    if not facts:
        facts = _current_state_facts(case_data, record)
    draft = _naturalize_fact_text(dialog_result.get("content"))
    if draft:
        facts.append(f"规则草稿中已经表达的病例事实: {draft}")
    seen = set()
    unique = []
    for item in facts:
        key = re.sub(r"\s+", "", item)
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


async def require_llm_patient_reply(case_data, record, student_message, dialog_result):
    """Force the final patient-facing answer through the LLM API.

    Rule code only decides the allowed fact boundary. The returned content must
    be generated by the API so the virtual patient sounds like a person while
    keeping triage-critical facts grounded in the case.
    """
    facts = _allowed_fact_pack(case_data, record or {}, dialog_result or {})
    fact_pack = "\n".join(f"- {item}" for item in facts) or "- 暂无可新增披露的病例事实"
    draft = _naturalize_fact_text((dialog_result or {}).get("content"))
    question_type = (dialog_result or {}).get("question_type") or classifyQuestionType(student_message)
    mode = (record or {}).get("mode", "practice")

    system_prompt = """你是急诊预检分诊训练系统中的真实患者或家属。
你的任务不是判断分诊，也不是给医学建议，而是用普通患者口吻回答护士问题。

硬性边界：
1. 关键医学事实只能来自【允许披露的病例事实】和【规则草稿】。
2. 不得新增诊断、治疗、检查结果、生命体征、分诊等级、就诊区域或病例没有的高危信息。
3. 必须把有助于护士预检分诊判断的核心信息说出来，例如起病时间、部位、诱因、伴随症状、否认项、疼痛程度、当前变化等。
4. 允许自然表达：可以使用“嗯”“大概”“我记得”“好像”“有点担心”“就是挺难受的”等语气和情绪。
5. 禁止说“病例信息中”“系统未提供”“根据资料”“无法回答”“你还是问医生吧”“请问具体一点”。
6. 如果护士问诊断，患者不能下诊断，只能说自己不知道，需要医护帮忙看看。
7. 默认称呼对方为“护士”或“您”，不要称呼“医生”。
8. 输出 1-2 句，只输出患者/家属说的话。"""

    user_prompt = f"""护士问题：
{student_message}

问题类型：{question_type}
训练模式：{mode}

允许披露的病例事实：
{fact_pack}

规则草稿：
{draft or "患者不确定，但仍需围绕当前不适自然回答。"}

请基于上述事实，生成一句或两句拟人化患者回答。"""

    content = await call_llm(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0.72,
        max_tokens=180,
        timeout=20,
        max_retries=1,
        purpose="triage_patient_required",
        log_meta={
            "case_id": case_data.get("case_id") or case_data.get("id") or case_data.get("external_id"),
            "record_id": (record or {}).get("id"),
            "base_reply_mode": (dialog_result or {}).get("reply_mode"),
            "question_type": question_type,
        },
    )
    sanitized, violations = sanitize_triage_reply(content)
    try:
        from services.triage_llm_patient import _guard_against_unsupported_medical_facts
        sanitized, fact_violations = _guard_against_unsupported_medical_facts(
            sanitized,
            facts,
            student_message,
        )
        violations.extend(fact_violations)
    except Exception:
        pass
    finalized = _finalize_reply(sanitized, case_data, record, question_type)
    if not finalized:
        raise RuntimeError("LLM returned empty patient reply")
    result = dict(dialog_result or {})
    result["content"] = finalized
    result["reply_mode"] = f"{result.get('reply_mode', 'patient')}_llm_api"
    result["llm_called"] = True
    result["llm_violations"] = violations
    return result


def _diagnostic_reply(case_data):
    complaint = _clean_fact((case_data.get("initial_exposure") or {}).get("chief_complaint"))
    if complaint:
        return f"这个我不清楚，我只是觉得{complaint}，需要你们帮我看看。"
    return "这个我不清楚，我只是觉得不舒服，需要你们帮我看看。"


def _out_of_scope_reply(case_data):
    complaint = _clean_fact((case_data.get("initial_exposure") or {}).get("chief_complaint"))
    if complaint:
        return f"这个我不太清楚，我现在主要是{complaint}。"
    return "这个我不太清楚，我现在就是觉得不舒服。"

async def generate_triage_patient_reply(case_data, record, student_message):
    """统一回答入口

    Returns: {
        "content": str, "reply_mode": str, "matched_intents": list,
        "matched_slots": list, "disclosed_slots": list,
        "should_append_disclosed": bool, "violations": list
    }
    """
    record = dict(record or {})
    record["_current_student_message"] = student_message
    disclosed = record.get("disclosed_slots", [])
    state_machine = case_data.get("dialogue_state_machine", {})
    all_slots = state_machine.get("slots", [])
    policy = state_machine.get("disclosure_policy", {})
    variant_id = record.get("variant_id", "default")

    intents = match_intent(student_message)
    intent_ids = [i["intent_id"] for i in intents] if intents else []
    question_type = classifyQuestionType(student_message)
    answer_policy = _answer_policy(question_type)

    if answer_policy["must_not_diagnose"]:
        reply = _finalize_reply(_diagnostic_reply(case_data), case_data, record, question_type)
        return {"content": reply, "reply_mode": "diagnostic_policy",
                "matched_intents": intent_ids, "matched_slots": [],
                "disclosed_slots": disclosed, "should_append_disclosed": False,
                "violations": [], "question_type": question_type}

    if _is_mechanical_trigger_question(student_message):
        matched_trigger_slots = []
        for intent_id in ["ask_trauma_detail", "ask_aggravating_relieving"]:
            slot = _select_best_slot(intent_id, all_slots, disclosed, case_data)
            if slot:
                matched_trigger_slots.append(slot.get("slot_id"))
                break
        if matched_trigger_slots:
            disclosed = _append_disclosed(disclosed, _unique_list(matched_trigger_slots))
        reply = _finalize_reply(_mechanical_trigger_reply(case_data, student_message), case_data, record, "trigger_question")
        return {"content": reply, "reply_mode": "mechanical_trigger_policy",
                "matched_intents": _unique_list(intent_ids + ["ask_trauma_detail"]),
                "matched_slots": matched_trigger_slots,
                "disclosed_slots": disclosed,
                "should_append_disclosed": bool(matched_trigger_slots),
                "violations": [], "question_type": "trigger_question"}

    if answer_policy["prefer_trigger_answer"]:
        reply = _finalize_reply(_natural_trigger_reply(case_data, disclosed, student_message), case_data, record, question_type)
        matched_trigger_slots = []
        for intent in intents[:2]:
            slot = _select_best_slot(intent["intent_id"], all_slots, disclosed, case_data)
            if slot:
                matched_trigger_slots.append(slot.get("slot_id"))
        if matched_trigger_slots:
            disclosed = _append_disclosed(disclosed, _unique_list(matched_trigger_slots))
        return {"content": reply, "reply_mode": "trigger_policy",
                "matched_intents": intent_ids, "matched_slots": matched_trigger_slots,
                "disclosed_slots": disclosed, "should_append_disclosed": bool(matched_trigger_slots),
                "violations": [], "question_type": question_type}

    if _asks_current_state_detail(student_message):
        reply = _current_state_targeted_reply(case_data, record)
        return {"content": _finalize_reply(reply, case_data, record, "subjective_question"),
                "reply_mode": "current_state_policy",
                "matched_intents": intent_ids, "matched_slots": [],
                "disclosed_slots": disclosed, "should_append_disclosed": False,
                "violations": [], "question_type": question_type}

    if question_type == "subjective_question" and not intent_ids:
        reply = _subjective_reply(case_data, record)
        return {"content": reply, "reply_mode": "subjective_policy",
                "matched_intents": intent_ids, "matched_slots": [],
                "disclosed_slots": disclosed, "should_append_disclosed": False,
                "violations": [], "question_type": question_type}

    # ── 第1层：操作类回应 ──
    if _is_operation_input(student_message):
        reply = random.choice(OPERATION_REPLIES)
        return {"content": reply, "reply_mode": "operation", "matched_intents": ["ask_vital_measure_permission"],
                "matched_slots": [], "disclosed_slots": disclosed,
                "should_append_disclosed": False, "violations": [], "question_type": question_type}

    # ── 第2层：slot 精准匹配 + LLM 自然化 ──
    matched = []
    seen_slot_ids = set()
    if intents:
        for intent in intents:
            slot = _select_best_slot(intent["intent_id"], all_slots, disclosed, case_data)
            if slot and slot.get("slot_id") not in seen_slot_ids:
                matched.append(slot)
                seen_slot_ids.add(slot.get("slot_id"))
            if len(matched) >= 2:
                break

    if question_type == "subjective_question" and not matched:
        reply = _subjective_reply(case_data, record)
        return {"content": reply, "reply_mode": "subjective_policy",
                "matched_intents": intent_ids, "matched_slots": [],
                "disclosed_slots": disclosed, "should_append_disclosed": False,
                "violations": [], "question_type": question_type}

    if matched:
        new_slots = _unique_list([m.get("slot_id") for m in matched])
        use_llm = os.getenv("TRIAGE_USE_LLM", "true").lower() in ("1", "true", "yes")

        if use_llm:
            try:
                from services.triage_llm_patient import generate_patient_reply
                llm_result = await generate_patient_reply(
                    case_data, disclosed, variant_id, student_message,
                    record.get("messages", []), new_slots)
                content = llm_result.get("content", "")
                if content and content not in ("这个我说不太清楚。",):
                    sanitized, violations = sanitize_triage_reply(content)
                    violations = list(llm_result.get("violations", []) or []) + violations
                    sanitized = _finalize_reply(sanitized, case_data, record, question_type)
                    disclosed = _append_disclosed(disclosed, new_slots)
                    return {"content": sanitized, "reply_mode": "slot_llm",
                            "matched_intents": intent_ids, "matched_slots": new_slots,
                            "disclosed_slots": disclosed, "should_append_disclosed": True,
                            "violations": violations, "question_type": question_type}
            except Exception:
                pass

        # LLM失败或关闭 → 规则自然化
        reply = _finalize_reply(_combine_slot_facts(matched, student_message, case_data, record), case_data, record, question_type)
        disclosed = _append_disclosed(disclosed, new_slots)
        return {"content": reply, "reply_mode": "slot_rule", "matched_intents": intent_ids,
                "matched_slots": new_slots, "disclosed_slots": disclosed,
                "should_append_disclosed": True, "violations": [], "question_type": question_type}

    # ── 第3层：slot label 模糊匹配 ──
    fuzzy = _fuzzy_match_slot(student_message, all_slots)
    if fuzzy and fuzzy["slot_id"] not in disclosed:
        reply = _finalize_reply(_combine_slot_facts([fuzzy], student_message, case_data, record), case_data, record, question_type)
        disclosed = _append_disclosed(disclosed, [fuzzy["slot_id"]])
        return {"content": reply, "reply_mode": "fuzzy_match", "matched_intents": [],
                "matched_slots": [fuzzy["slot_id"]], "disclosed_slots": disclosed,
                "should_append_disclosed": True, "violations": [], "question_type": question_type}

    # ── 第4层：V1兜底 (旧 required_questions) ──
    from services.triage_patient_v1 import match_question
    asked = record.get("asked_questions", [])
    v1_result = match_question(case_data, student_message, asked)
    if v1_result.get("matched") and not v1_result.get("already_asked"):
        reply = v1_result["answer"]
        # 过滤占位答案，避免返回"根据病例资料回答。"
        if _is_placeholder_fact(reply) or _is_generic_initial_fact(reply, case_data):
            reply = _get_role_fallback("general")
        reply = _finalize_reply(reply, case_data, record, question_type)
        return {"content": reply, "reply_mode": "v1_fallback", "matched_intents": [],
                "matched_slots": [], "disclosed_slots": disclosed,
                "should_append_disclosed": False, "violations": [], "question_type": question_type}

    # ── 第5层：LLM 受控兜底 ──
    use_llm = os.getenv("TRIAGE_USE_LLM", "true").lower() in ("1", "true", "yes")
    if use_llm:
        try:
            from services.triage_llm_patient import generate_patient_reply
            llm_result = await generate_patient_reply(
                case_data, disclosed, variant_id, student_message,
                record.get("messages", []), None)
            content = llm_result.get("content", "")
            if content and len(content) > 3:
                sanitized, violations = sanitize_triage_reply(content)
                violations = list(llm_result.get("violations", []) or []) + violations
                sanitized = _finalize_reply(sanitized, case_data, record, question_type)
                return {"content": sanitized, "reply_mode": "llm_semantic", "matched_intents": [],
                        "matched_slots": [], "disclosed_slots": disclosed,
                        "should_append_disclosed": False, "violations": violations, "question_type": question_type}
        except Exception:
            pass

    # ── 第6层：角色化不知道（最后兜底）──
    category = "general"
    if any(kw in student_message for kw in ["药","吃药","降压","降糖"]):
        category = "medication"
    elif any(kw in student_message for kw in ["什么时候","多久","几点","开始"]):
        category = "time_detail"
    elif any(kw in student_message for kw in ["以前","过去","病史","得过","诊断"]):
        category = "history"
    if question_type == "out_of_scope_question":
        reply = _out_of_scope_reply(case_data)
    else:
        reply = _get_role_fallback(category)
    reply = _finalize_reply(reply, case_data, record, question_type)
    return {"content": reply, "reply_mode": "role_fallback", "matched_intents": [],
            "matched_slots": [], "disclosed_slots": disclosed,
            "should_append_disclosed": False, "violations": [], "question_type": question_type}
