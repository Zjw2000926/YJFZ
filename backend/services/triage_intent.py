"""V2 学员提问意图识别

两层识别策略：
1. 规则优先：关键词、同义词匹配
2. LLM 兜底：仅输出意图 ID（速度快，成本低）
"""

import json
import os
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTENTS_PATH = os.path.join(BASE_DIR, "triage_data", "intents", "triage_intents_v1.json")

_intents_cache = None


TRAUMA_CONTEXT_TERMS = (
    "撞", "撞到", "撞击", "摔", "跌", "车祸", "事故", "外伤", "受伤",
    "割", "刀", "玻璃", "扭伤", "扭到", "砸", "碰撞", "碰到", "搬重物", "搬东西",
)

HEAD_INJURY_CONTEXT_TERMS = (
    "头部外伤", "头有没有撞", "头撞", "撞到头", "摔到头", "头部撞",
    "头部受伤", "头部", "撞", "摔", "跌", "车祸", "外伤",
)


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _load_intents() -> list:
    global _intents_cache
    if _intents_cache is None:
        with open(INTENTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _intents_cache = data.get("intents", [])
    return _intents_cache


def match_intent_by_keyword(student_message: str) -> list:
    """规则优先：关键词匹配意图。

    Returns:
        [{"intent_id": "ask_onset_time", "confidence": 1.0, "matched_by": "keyword"}, ...]
    """
    intents = _load_intents()
    matched = []
    msg_lower = student_message.lower()

    for intent in intents:
        keywords = intent.get("keywords", [])
        for kw in keywords:
            if kw in student_message:
                intent_id = intent["id"]
                if intent_id == "ask_trauma_detail" and not _has_any(student_message, TRAUMA_CONTEXT_TERMS):
                    continue
                if intent_id == "ask_head_injury" and not _has_any(student_message, HEAD_INJURY_CONTEXT_TERMS):
                    continue
                matched.append({
                    "intent_id": intent_id,
                    "label": intent["label"],
                    "confidence": 0.9,
                    "matched_by": "keyword",
                })
                break  # 同一个意图只匹配一次

    return matched


def _append_match(matches: list, intent_id: str, label: str = "", confidence: float = 0.72):
    if any(item.get("intent_id") == intent_id for item in matches):
        return
    matches.append({
        "intent_id": intent_id,
        "label": label or intent_id,
        "confidence": confidence,
        "matched_by": "semantic_rule",
    })


def match_intent_by_semantic_rule(student_message: str) -> list:
    """Lightweight Chinese natural-question mapping for common triage wording.

    This deliberately stays rule-based: it improves scoring/dialogue coverage
    without letting an LLM invent medical facts.
    """
    text = str(student_message or "").strip().lower()
    matches = []

    if any(word in text for word in ["现在感觉", "感觉怎么样", "现在怎么样", "怎么样了", "还好吗", "难受吗"]):
        _append_match(matches, "ask_severity", "当前严重程度")
        _append_match(matches, "ask_aggravating_relieving", "症状变化")

    if any(word in text for word in [
        "有没有变化", "有变化", "加重了吗", "减轻了吗", "有没有加重", "有没有缓解",
        "比刚才", "比之前", "疼痛比", "疼得更", "更疼", "新的不舒服", "新症状",
        "坐不住", "受不了了", "疼痛几分", "现在疼痛", "疼痛评分",
    ]):
        _append_match(matches, "ask_aggravating_relieving", "症状变化")
        _append_match(matches, "ask_severity", "当前严重程度")

    if any(word in text for word in ["以前有过", "以前这样", "之前有过", "过去有过", "从来没有过", "第一次这样", "手术", "开刀", "住院", "手术史"]):
        _append_match(matches, "ask_past_history", "既往类似情况")

    if any(word in text for word in ["什么原因", "为什么", "诱因", "什么引起", "怎么引起", "吃坏东西", "吃东西后"]):
        _append_match(matches, "ask_aggravating_relieving", "诱因/加重缓解")

    if any(word in text for word in ["撞击", "撞到", "碰撞", "碰到", "撞伤", "外伤", "搬东西", "搬重物", "扭伤", "扭到"]):
        _append_match(matches, "ask_trauma_detail", "外伤/搬重物诱因")
        _append_match(matches, "ask_aggravating_relieving", "诱因/加重缓解")

    if any(word in text for word in ["为什么现在才来", "为什么才来", "现在才来医院", "拖到现在"]):
        _append_match(matches, "ask_onset_time", "起病时间")
        _append_match(matches, "ask_duration", "持续时间")

    if any(word in text for word in ["有没有别的症状", "还有哪里", "还有什么", "伴随", "恶心", "呕吐", "头晕", "出汗"]):
        _append_match(matches, "ask_accompanying", "伴随症状")

    if any(word in text for word in ["冷汗", "出汗", "冒汗", "大汗"]):
        _append_match(matches, "ask_sweating", "出冷汗")

    return matches


def match_intent(student_message: str) -> list:
    """意图识别主入口。

    V2 先用关键词匹配。如果没有命中，返回空列表，
    路由层可决定是否走 LLM 兜底。

    Returns:
        匹配的意图列表，按置信度降序排列
    """
    keyword_matches = match_intent_by_keyword(student_message)
    semantic_matches = match_intent_by_semantic_rule(student_message)
    for item in semantic_matches:
        if not any(existing.get("intent_id") == item.get("intent_id") for existing in keyword_matches):
            keyword_matches.append(item)
    return keyword_matches


async def match_intent_llm_fallback(student_message: str) -> list:
    """LLM 兜底识别（仅在关键词无匹配时调用）。

    使用轻量级 LLM 调用，仅输出意图 ID 数组。
    """
    # V2 初期：如果关键词没命中，直接返回空
    # 避免额外 LLM 调用延迟
    return []


def get_intent_by_id(intent_id: str) -> Optional[dict]:
    """根据意图 ID 获取意图定义"""
    intents = _load_intents()
    for intent in intents:
        if intent["id"] == intent_id:
            return intent
    return None


def get_intent_slot_mapping() -> dict:
    """获取意图 ID 到 slot_id 的映射规则。

    由病例的 dialogue_state_machine.slots[].canonical_intents 定义，
    此函数从所有已加载病例中聚合映射。
    """
    # 简单映射：意图 ID 通常对应 slot_id 去掉 "ask_" 前缀
    mapping = {}
    intents = _load_intents()
    for intent in intents:
        iid = intent["id"]
        if iid.startswith("ask_"):
            slot_id = iid[4:]  # 去掉 ask_ 前缀
        else:
            slot_id = iid
        mapping[iid] = slot_id
    return mapping
