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
                matched.append({
                    "intent_id": intent["id"],
                    "label": intent["label"],
                    "confidence": 0.9,
                    "matched_by": "keyword",
                })
                break  # 同一个意图只匹配一次

    return matched


def match_intent(student_message: str) -> list:
    """意图识别主入口。

    V2 先用关键词匹配。如果没有命中，返回空列表，
    路由层可决定是否走 LLM 兜底。

    Returns:
        匹配的意图列表，按置信度降序排列
    """
    keyword_matches = match_intent_by_keyword(student_message)
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
