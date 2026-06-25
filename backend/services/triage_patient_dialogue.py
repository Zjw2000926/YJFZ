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
        "药名我记不太清了，平时吃的药家属可能知道。",
        "好像叫什么地平还是普利的，我记不清全名。",
        "降压药，具体叫什么我不太确定。",
    ],
    "time_detail": [
        "我说不太清楚具体几点开始的，大概就是刚才那一阵。",
        "差不多就刚才吧，具体什么时间我记不太清。",
    ],
    "history": [
        "以前好像查过，但结果我不太清楚，可能家属知道。",
        "这个我不确定，以前医生说过但没记住。",
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


def _strip_sentence_end(text):
    return re.sub(r"[。！？.!?；;，,、\s]+$", "", _clean_fact(text))


def _combine_slot_facts(slots):
    """把命中的病例事实合成患者回答；不使用占位事实，不重复同一句。"""
    facts = []
    seen = set()
    for slot in slots[:2]:
        fact = _first_fact(slot)
        if _is_placeholder_fact(fact):
            continue
        key = re.sub(r"\s+", "", fact)
        if key in seen:
            continue
        seen.add(key)
        facts.append(fact)
    if not facts:
        return "这个我说不太清楚。"
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
        facts = [_clean_fact(f) for f in slot.get("answer_facts", []) or [] if _clean_fact(f)]
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
        reply = _diagnostic_reply(case_data)
        return {"content": reply, "reply_mode": "diagnostic_policy",
                "matched_intents": intent_ids, "matched_slots": [],
                "disclosed_slots": disclosed, "should_append_disclosed": False,
                "violations": [], "question_type": question_type}

    if answer_policy["prefer_trigger_answer"]:
        reply = _natural_trigger_reply(case_data, disclosed, student_message)
        return {"content": reply, "reply_mode": "trigger_policy",
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
                    disclosed = _append_disclosed(disclosed, new_slots)
                    return {"content": sanitized, "reply_mode": "slot_llm",
                            "matched_intents": intent_ids, "matched_slots": new_slots,
                            "disclosed_slots": disclosed, "should_append_disclosed": True,
                            "violations": violations, "question_type": question_type}
            except Exception:
                pass

        # LLM失败或关闭 → 规则自然化
        reply = _combine_slot_facts(matched)
        disclosed = _append_disclosed(disclosed, new_slots)
        return {"content": reply, "reply_mode": "slot_rule", "matched_intents": intent_ids,
                "matched_slots": new_slots, "disclosed_slots": disclosed,
                "should_append_disclosed": True, "violations": [], "question_type": question_type}

    # ── 第3层：slot label 模糊匹配 ──
    fuzzy = _fuzzy_match_slot(student_message, all_slots)
    if fuzzy and fuzzy["slot_id"] not in disclosed:
        reply = _combine_slot_facts([fuzzy])
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
    return {"content": reply, "reply_mode": "role_fallback", "matched_intents": [],
            "matched_slots": [], "disclosed_slots": disclosed,
            "should_append_disclosed": False, "violations": [], "question_type": question_type}
