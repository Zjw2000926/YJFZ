"""V2 LLM 虚拟患者控制器

回答生成流程：
学生问题 → 意图识别 → 状态机找可披露slot → LLM生成自然语言 → 安全检查 → 保存

LLM 只能收到：
1. 固定患者角色规则
2. 当前病例已允许披露的信息槽
3. 患者表达风格
4. 当前学生问题 + 最近少量对话上下文

不能给 LLM 完整病例底稿（尤其是分诊等级、诊断、评分标准）
"""

import os
import re
from typing import Optional
from services.triage_intent import match_intent
from services.triage_guard import sanitize_triage_reply
from services.llm_service import call_llm


CONTROLLED_FACT_PROMPT = """【受控事实包规则】
你只是把【已允许披露的信息】改写成患者口吻，不是自由问答。
事实层必须严格：不得新增未列出的症状、病史、检查值、诊断、处置、分诊等级或病情判断。
表达层可以自然：允许使用“我也说不太清楚”“好像”“有点担心”“就是突然不舒服”等语气和情绪，只要不增加新的关键医学事实。
如果护士问原因/诱因而事实包没有明确诱因，不要编造吃饭、运动、外伤等具体诱因；应自然回答“不确定为什么，就是那会儿开始不舒服，好像没有特别明显的诱因”。
如果护士问“是不是某个病/诊断”，患者不能给医学判断，只能说“不清楚，需要你们帮我看看”。
不要说“根据病例资料”“病例显示”“资料中写着”“系统未提供”等破坏沉浸感的话。
输出 1-2 句，口语化，像真实患者。"""


CONTROLLED_FACT_PROMPT = """
【事实受控、表达自然规则】
你扮演真实患者或家属，不是系统、医生、教师或评分员。

1. 医学事实层必须严格基于【已允许披露的信息】：
- 年龄、性别、起病时间、疼痛部位、症状、既往史、用药、过敏、检查/生命体征等关键事实，只能使用已列出的内容。
- 不得新增诊断、检查结果、治疗方案、分诊等级、就诊区域或评分依据。

2. 患者表达层必须自然：
- 不要逐字照抄字段，必须改写成普通患者会说的话。
- 可以使用“嗯”“大概”“我记得”“好像”“说不太准”“有点担心”“就是挺难受的”等自然语气。
- 可以表达焦虑、疼痛、犹豫、记不清，但不能借此新增关键病情。

3. 问到原因/诱因：
- 已允许信息里有诱因，就用患者口吻说出来，并可补一句“具体是不是这个引起的我也不确定”。
- 没有诱因信息，只能说“不太清楚/没注意到明显诱因”，不能编造饮食、外伤、运动等。

4. 问到诊断：
- 患者不能判断“是不是某某病”，只能说“不清楚，需要你们帮我看看”。

5. 禁止输出：
- “病例信息中”“系统未提供”“根据资料”“无法回答”“你还是问医生吧”等破坏沉浸感的话。

输出 1-2 句，口语化，像真实患者正在回答护士。
"""


def _normalize_slot_ids(new_slot_id) -> list:
    if not new_slot_id:
        return []
    if isinstance(new_slot_id, (list, tuple, set)):
        return [str(sid) for sid in new_slot_id if sid]
    return [str(new_slot_id)]


def _clean_fact(fact):
    return str(fact or "").strip()


def _is_placeholder_fact(fact):
    cleaned = _clean_fact(fact)
    return not cleaned or cleaned in {
        "根据病例资料回答。",
        "根据病例资料回答",
        "根据病例资料回答该项内容。",
        "根据病例资料回答该项内容",
    }


def _facts_from_slot(slot) -> list:
    facts = []
    for fact in slot.get("answer_facts", []) or []:
        cleaned = _clean_fact(fact)
        if cleaned and not _is_placeholder_fact(cleaned):
            facts.append(cleaned)
    return facts


def _case_initial_texts(case_data):
    initial = case_data.get("initial_exposure", {}) or {}
    return {
        _clean_fact(initial.get("chief_complaint")),
        _clean_fact(initial.get("opening_line")),
    } - {""}


def _slot_quality(slot, case_data):
    facts = _facts_from_slot(slot)
    first_fact = facts[0] if facts else ""
    score = 0
    if facts:
        score += 20
    if first_fact and first_fact not in _case_initial_texts(case_data):
        score += 15
    if not str(slot.get("slot_id", "")).startswith("slot_"):
        score += 8
    if slot.get("is_required"):
        score += 2
    if slot.get("label"):
        score += 1
    return score


def _select_best_slot(intent_id, all_slots, disclosed_slots, case_data):
    candidates = [
        slot for slot in all_slots
        if intent_id in slot.get("canonical_intents", [])
        and slot.get("slot_id") not in disclosed_slots
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda slot: _slot_quality(slot, case_data))


def _slots_by_ids(case_data, slot_ids):
    state_machine = case_data.get("dialogue_state_machine", {})
    all_slots = state_machine.get("slots", [])
    by_id = {slot.get("slot_id"): slot for slot in all_slots}
    return [by_id[sid] for sid in slot_ids if sid in by_id]


def _unique_facts(slots) -> list:
    facts = []
    seen = set()
    for slot in slots:
        for fact in _facts_from_slot(slot):
            key = re.sub(r"\s+", "", fact)
            if key in seen:
                continue
            seen.add(key)
            facts.append(fact)
    return facts


def _normalize_reply_text(reply):
    reply = re.sub(r"。{2,}", "。", reply or "")
    reply = reply.replace("。”。", "。”")
    return reply.strip()


def _strip_sentence_end(text):
    return re.sub(r"[。！？.!?；;，,、\s]+$", "", _clean_fact(text))


def _patientize_facts(facts, question="") -> str:
    cleaned = []
    seen = set()
    for fact in facts:
        text = _strip_sentence_end(_clean_fact(fact)).strip("“”\"'")
        if not text:
            continue
        key = re.sub(r"\s+", "", text)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    if not cleaned:
        return "这个我一时说不太清楚，就是现在不太舒服。"

    q = str(question or "")
    joined = "，".join(cleaned[:2])
    first = cleaned[0]
    if any(term in q for term in ("撞击", "撞到", "碰撞", "碰到", "撞伤", "外伤")) and "搬" in joined:
        return _normalize_reply_text(f"不是被东西撞到，我记得是{joined}。")
    if any(term in q for term in ("搬东西", "搬重物", "搬箱子", "扭伤", "扭到")) and "搬" in joined:
        return _normalize_reply_text(f"对，就是{joined}。")
    if any(term in q for term in ("有没有", "有无", "是否", "是吗", "的吗", "吗")):
        if any(term in joined for term in ("没有", "无", "否认", "未见")):
            return _normalize_reply_text(f"没有，我目前能说清的就是{joined}。")
        return _normalize_reply_text(f"嗯，有的，{joined}。")
    if any(term in q for term in ("什么时候", "多久", "多长时间", "几点", "开始", "起病")):
        return _normalize_reply_text(f"大概就是{first}，具体时间我也只能按感觉说个大概。")
    if any(term in q for term in ("哪里", "哪个位置", "部位", "位置", "哪儿")):
        return _normalize_reply_text(f"主要就是{first}，我自己感觉这个地方最明显。")
    if len(cleaned) > 1:
        return _normalize_reply_text(f"我现在主要就是{cleaned[0]}，另外{cleaned[1]}。")
    return _normalize_reply_text(f"我现在主要就是{first}，有点不舒服，也有点担心。")


def _fallback_from_slots(slots, question="") -> str:
    facts = _unique_facts(slots)
    if not facts:
        return "这个我说不太清楚。"
    return _patientize_facts(facts, question)
    sentences = []
    for fact in facts[:2]:
        if fact.endswith(("。", "！", "？", "…", ".", "!", "?")):
            sentences.append(fact)
        else:
            sentences.append(f"{fact}。")
    return _normalize_reply_text("".join(sentences))


def _build_allowed_info(disclosed_slots: list, case_data: dict,
                        new_slot_id: Optional[str] = None) -> str:
    """构建【已允许披露的信息】文本（仅供 LLM 参考）"""
    state_machine = case_data.get("dialogue_state_machine", {})
    all_slots = state_machine.get("slots", [])
    allowed_slot_ids = set(disclosed_slots or []) | set(_normalize_slot_ids(new_slot_id))

    lines = []
    for slot in all_slots:
        sid = slot.get("slot_id")
        if sid in allowed_slot_ids:
            facts = _facts_from_slot(slot)
            facts_text = "；".join(facts) if facts else "患者未提供更多具体信息"
            lines.append(f"- {slot.get('label', sid)}：{facts_text}")

    if not lines:
        return "暂无新增可披露信息"

    return "\n".join(lines)


def build_triage_llm_messages(
    case_data: dict,
    disclosed_slots: list,
    variant_id: str,
    student_message: str,
    history_messages: list = None,
    new_slot_id: Optional[str] = None,
) -> list:
    """构建预检分诊 LLM messages。

    与虚拟患者提示词体系（backend/prompts/）设计原则一致：
    - messages[0]: system = 固定角色规则 + 已允许披露信息 + 表达风格
    - messages[1..]: user/assistant 对话历史
    - messages[-1]: user = 当前学生问题
    """
    from prompts.triage_patient_system_prompt import TRIAGE_PATIENT_SYSTEM_PROMPT, VARIANT_STYLES

    # System prompt
    system = TRIAGE_PATIENT_SYSTEM_PROMPT

    # 已允许披露的信息
    allowed = _build_allowed_info(disclosed_slots, case_data, new_slot_id)
    system += f"\n\n【已允许披露的信息】\n{allowed}"
    system += f"\n\n{CONTROLLED_FACT_PROMPT}"

    # 表达风格
    variant = case_data.get("patient_variants") or [{"variant_id": "default"}]
    style = VARIANT_STYLES.get(variant_id, VARIANT_STYLES["default"])
    active_variant = next((v for v in variant if v.get("variant_id") == variant_id), variant[0])
    comm_style = active_variant.get("communication_style", "")
    speaker = active_variant.get("speaker_role", "patient")
    system += f"\n\n【表达风格】\n{style}"
    if comm_style:
        system += f" {comm_style}"
    if speaker == "family":
        system += "\n重要：你当前以家属身份代述，不确定的信息用'好像''可能'。"

    messages = [{"role": "system", "content": system}]

    # 对话历史（最近 4 轮）
    if history_messages:
        recent = history_messages[-8:] if len(history_messages) > 8 else history_messages
        for msg in recent:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "student":
                messages.append({"role": "user", "content": content})
            elif role == "patient":
                messages.append({"role": "assistant", "content": content})

    # 当前问题
    messages.append({"role": "user", "content": student_message})

    return messages


async def generate_patient_reply(
    case_data: dict,
    disclosed_slots: list,
    variant_id: str,
    student_message: str,
    history_messages: list = None,
    new_slot_id: Optional[str] = None,
) -> dict:
    """生成虚拟患者自然语言回答。

    Returns:
        {
            "content": "患者回答文本",
            "matched_intents": [...],
            "disclosed_slot": "slot_id" or None,
            "disclosure_layer": "L0"|"L1"|"L2"|"L3"|None,
            "violations": []
        }
    """
    # 1. 意图识别
    intents = match_intent(student_message)

    # 2. 状态机：找可披露的 slot
    state_machine = case_data.get("dialogue_state_machine", {})
    all_slots = state_machine.get("slots", [])
    policy = state_machine.get("disclosure_policy", {})

    explicit_slot_ids = _normalize_slot_ids(new_slot_id)
    matched_slots = _slots_by_ids(case_data, explicit_slot_ids)

    if not matched_slots and intents:
        # 意图 → slot 映射
        seen_slot_ids = set()
        for intent in intents:
            iid = intent["intent_id"]
            slot = _select_best_slot(iid, all_slots, disclosed_slots, case_data)
            if slot and slot.get("slot_id") not in seen_slot_ids:
                matched_slots.append(slot)
                seen_slot_ids.add(slot.get("slot_id"))
            if len(matched_slots) >= 2:
                break

    # 3. 生成回答
    if matched_slots:
        # 从 answer_facts 直接生成（规则模式，不调 LLM 也能用）
        facts = _unique_facts(matched_slots)
        if not facts:
            reply_content = _fallback_from_slots(matched_slots, student_message)
        elif not _should_use_llm(case_data):
            reply_content = _fallback_from_slots(matched_slots, student_message)
        else:
            # LLM 模式
            try:
                selected_ids = [slot.get("slot_id") for slot in matched_slots if slot.get("slot_id")]
                messages = build_triage_llm_messages(
                    case_data, disclosed_slots, variant_id,
                    student_message, history_messages, selected_ids)
                reply_content = await call_llm(
                    messages, temperature=0.68, max_tokens=160, timeout=20,
                    purpose="triage_patient", max_retries=1)
                if not _clean_fact(reply_content):
                    reply_content = _fallback_from_slots(matched_slots, student_message)
            except Exception:
                reply_content = _fallback_from_slots(matched_slots, student_message)
    else:
        # 未命中：温和兜底
        if policy.get("unknown_policy") == "patient_uncertain":
            reply_content = "这个我不太清楚，您能再问得具体一点吗？"
        else:
            reply_content = "这方面我说不太准，您还是问医生吧。"

    # 4. 安全检查
    sanitized, violations = sanitize_triage_reply(reply_content)

    # 5. 返回结果
    return {
        "content": sanitized,
        "matched_intents": [i["intent_id"] for i in intents] if intents else [],
        "disclosed_slot": matched_slots[0].get("slot_id") if matched_slots else None,
        "disclosed_slots": [slot.get("slot_id") for slot in matched_slots if slot.get("slot_id")],
        "disclosure_layer": matched_slots[0].get("layer") if matched_slots else None,
        "grounding_slot_ids": [slot.get("slot_id") for slot in matched_slots if slot.get("slot_id")],
        "grounding_facts": _unique_facts(matched_slots),
        "violations": violations,
    }


def _should_use_llm(case_data: dict) -> bool:
    """Use LLM automatically when a key exists, while keeping an explicit off switch."""
    flag = os.getenv("TRIAGE_USE_LLM", "auto").lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return bool(os.getenv("DEEPSEEK_API_KEY")) or bool(case_data.get("_use_llm", False))
