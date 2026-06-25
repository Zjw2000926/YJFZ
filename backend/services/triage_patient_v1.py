"""预检分诊 V1 患者问答引擎

纯关键词匹配，不调用 LLM。
每个病例的 required_questions 定义了可回答的问题和关键词。
未命中时返回温和兜底。
"""

import ast
import random


def _format_measurement_value(value):
    """格式化生命体征值：将 Python 列表字符串等异常格式转为中文"""
    if value is None:
        return ""
    if isinstance(value, list):
        return "、".join(str(x).strip() for x in value if str(x).strip())
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    return "、".join(str(x).strip() for x in parsed if str(x).strip())
            except Exception:
                return text
        return text
    return str(value)


def _normalize_measurement(m):
    """标准化单个 measurement：格式化 value 并生成 display_value"""
    item = dict(m)
    item["value"] = _format_measurement_value(item.get("value"))
    item["display_value"] = item["value"]
    unit = item.get("unit") or ""
    if unit and item["display_value"]:
        item["display_value"] = f"{item['display_value']} {unit}"
    return item


UNKNOWN_REPLIES = [
    "这个我说不太清楚，您能再问得具体一点吗？",
    "这方面我不太了解，您还是问医生吧。",
    "我记不太清楚了，不好意思。",
    "这个我也说不好，您能换个方式问问吗？",
    "嗯……这个我没什么印象了。",
]

ALREADY_ASKED_REPLIES = [
    "我刚才说过了，就是那样。",
    "这个我刚才已经说了呀。",
    "没别的了，就是我刚才说的那个情况。",
]


def match_question(case_data: dict, student_message: str,
                   asked_questions: list) -> dict:
    """根据学生输入匹配病例的 required_questions。

    Args:
        case_data: 病例数据
        student_message: 学生输入文本
        asked_questions: 已经问过的问题 id 列表

    Returns:
        {"matched": bool, "answer": str, "question_id": str|None, "question_label": str|None}
    """
    questions = case_data.get("required_questions", [])
    if not questions:
        return {"matched": False, "answer": random.choice(UNKNOWN_REPLIES),
                "question_id": None, "question_label": None}

    msg_lower = student_message.lower()

    # 1. 按关键词匹配
    for q in questions:
        keywords = q.get("keywords", [])
        for kw in keywords:
            if kw in student_message:
                qid = q.get("id")
                if qid in asked_questions:
                    # 已问过 → 简短确认
                    return {"matched": True,
                            "answer": random.choice(ALREADY_ASKED_REPLIES),
                            "question_id": qid, "question_label": q.get("label"),
                            "already_asked": True}
                # 新问题 → 返回答案
                return {"matched": True, "answer": q.get("answer", ""),
                        "question_id": qid, "question_label": q.get("label"),
                        "already_asked": False}

    # 2. 模糊匹配：检查是否包含开放式提问
    open_keywords = ["怎么不舒服", "哪里不舒服", "什么情况", "跟我说说",
                     "详细说说", "具体", "能告诉我", "您的情况"]
    for kw in open_keywords:
        if kw in student_message:
            # 返回第一条未问过的问题
            for q in questions:
                qid = q.get("id")
                if qid not in asked_questions:
                    return {"matched": True, "answer": q.get("answer", ""),
                            "question_id": qid, "question_label": q.get("label"),
                            "already_asked": False}
            # 全问过了
            return {"matched": True,
                    "answer": "我把能说的都说了，你看看还有什么能帮我的吧。",
                    "question_id": None, "question_label": None, "already_asked": True}

    # 3. 兜底
    return {"matched": False, "answer": random.choice(UNKNOWN_REPLIES),
            "question_id": None, "question_label": None}


def get_vital_signs(case_data: dict, measurement_ids: list = None) -> list:
    """获取生命体征测量结果，自动格式化值。

    Args:
        case_data: 病例数据
        measurement_ids: 要测量的项目 id 列表，为空则返回全部

    Returns:
        测量结果列表（含 display_value 和格式化后的 value）
    """
    measurements = case_data.get("required_measurements", [])
    if not measurement_ids:
        return [_normalize_measurement(m) for m in measurements]

    result = []
    for m in measurements:
        if m.get("id") in measurement_ids:
            result.append(_normalize_measurement(m))
    return result
