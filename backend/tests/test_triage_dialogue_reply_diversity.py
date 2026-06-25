"""固定回复回归测试: 确认不同维度问题获得不同回答"""
import asyncio, os

os.environ["TRIAGE_USE_LLM"] = "false"

from services.triage_repository import get_case
from services.triage_patient_dialogue import classifyQuestionType, generate_triage_patient_reply


def _run_async(coro):
    return asyncio.run(coro)


def test_triage_006_replies_are_dimension_specific():
    """TRIAGE-006: 不同维度问题不应返回同一句话"""

    async def _test():
        case = get_case("TRIAGE-006")
        assert case, "TRIAGE-006 not found"

        record = {
            "id": "test_div",
            "case_external_id": "TRIAGE-006",
            "messages": [], "disclosed_slots": [], "variant_id": "default",
        }

        questions = {
            "chief": "哪里不舒服？",
            "time": "什么时候开始疼的？",
            "location": "具体哪个位置疼？",
            "accompanying": "有没有恶心出汗？",
            "history": "以前有心脏病吗？",
        }

        replies = {}
        for key, q in questions.items():
            result = await generate_triage_patient_reply(case, record, q)
            replies[key] = result["content"]
            if result.get("should_append_disclosed"):
                record["disclosed_slots"] = result["disclosed_slots"]

        unique = set(replies.values())
        assert len(unique) >= 4, f"{len(unique)} unique replies (need >=4): {replies}"
        assert any(kw in replies["time"] for kw in ["开始", "刚才", "分钟", "来"]), f"time: {replies['time']}"
        assert "没有" in replies["accompanying"], f"accompanying: {replies['accompanying']}"
        assert any(kw in replies["location"] for kw in ["位置", "块", "边", "前胸", "局部"]), f"location: {replies['location']}"

    asyncio.run(_test())


def test_reply_no_placeholder():
    """任何病例回复不应包含占位文本"""

    async def _test():
        case = get_case("TRIAGE-006")
        record = {
            "id": "test_ph",
            "case_external_id": "TRIAGE-006",
            "messages": [], "disclosed_slots": [], "variant_id": "default",
        }
        result = await generate_triage_patient_reply(case, record, "按压时疼吗？")
        assert "根据病例资料回答" not in result["content"], f"Placeholder: {result['content']}"

    asyncio.run(_test())


def test_reply_no_duplicate_sentence():
    """同一回复不应重复同一句子"""

    async def _test():
        case = get_case("TRIAGE-006")
        record = {
            "id": "test_rep",
            "case_external_id": "TRIAGE-006",
            "messages": [], "disclosed_slots": [], "variant_id": "default",
        }
        result = await generate_triage_patient_reply(case, record, "伴有恶心呕吐吗？")
        content = result["content"]
        sents = [s.strip() for s in content.replace("！", "。").replace("？", "。").split("。") if s.strip()]
        if len(sents) > 1:
            assert len(sents) == len(set(sents)), f"Duplicate sentences: {sents}"

    asyncio.run(_test())


def test_question_type_classifier_policy_boundaries():
    assert classifyQuestionType("什么原因引起你疼的？") == "trigger_question"
    assert classifyQuestionType("有没有什么诱因？") == "trigger_question"
    assert classifyQuestionType("你觉得是不是阑尾炎？") == "diagnostic_question"
    assert classifyQuestionType("什么时候开始疼？") == "factual_question"
    assert classifyQuestionType("现在感觉怎么样，有没有变化？") == "subjective_question"


def test_trigger_questions_use_natural_uncertainty_not_rigid_refusal():
    async def _test():
        case = get_case("TRIAGE-DYN-RLQ-001")
        assert case, "TRIAGE-DYN-RLQ-001 not found"
        banned = ["问医生", "病例信息", "系统未提供", "无法回答", "资料中"]

        questions = [
            "什么原因引起你疼的？",
            "有没有什么诱因？",
            "你觉得是不是吃坏东西了？",
            "你为什么现在才来医院？",
            "你以前有过这种情况吗？",
        ]
        for question in questions:
            record = {
                "id": f"trigger_{question}",
                "case_external_id": "TRIAGE-DYN-RLQ-001",
                "messages": [],
                "disclosed_slots": [],
                "variant_id": "default",
            }
            result = await generate_triage_patient_reply(case, record, question)
            content = result["content"]
            assert content.strip(), f"empty reply for {question}"
            assert not any(word in content for word in banned), f"rigid refusal for {question}: {content}"

        trigger_result = await generate_triage_patient_reply(case, {
            "id": "trigger_reason",
            "case_external_id": "TRIAGE-DYN-RLQ-001",
            "messages": [],
            "disclosed_slots": [],
            "variant_id": "default",
        }, "什么原因引起你疼的？")
        assert trigger_result["reply_mode"] == "trigger_policy"
        assert any(word in trigger_result["content"] for word in ["说不清楚", "不确定", "明显诱因", "开始"])

    asyncio.run(_test())


def test_diagnostic_question_does_not_invent_diagnosis():
    async def _test():
        case = get_case("TRIAGE-DYN-RLQ-001")
        record = {
            "id": "diagnostic",
            "case_external_id": "TRIAGE-DYN-RLQ-001",
            "messages": [],
            "disclosed_slots": [],
            "variant_id": "default",
        }
        result = await generate_triage_patient_reply(case, record, "你是不是阑尾炎？")
        assert result["reply_mode"] == "diagnostic_policy"
        assert "不清楚" in result["content"]
        assert "阑尾炎" not in result["content"]

    asyncio.run(_test())
