import asyncio


def _case(case_id="TRIAGE-006"):
    from services.triage_repository import get_case

    case = get_case(case_id)
    assert case is not None
    return case


def test_specific_slot_wins_over_repeated_opening_fact(monkeypatch):
    monkeypatch.setenv("TRIAGE_USE_LLM", "false")

    from services.triage_patient_dialogue import generate_triage_patient_reply

    result = asyncio.run(generate_triage_patient_reply(
        _case(),
        {"disclosed_slots": [], "messages": [], "variant_id": "default"},
        "什么时候开始疼的？",
    ))

    assert result["reply_mode"] == "slot_rule"
    assert result["matched_slots"] == ["onset_time"]
    assert "刚才" in result["content"]


def test_multi_intent_same_slot_is_deduplicated(monkeypatch):
    monkeypatch.setenv("TRIAGE_USE_LLM", "false")

    from services.triage_patient_dialogue import generate_triage_patient_reply

    result = asyncio.run(generate_triage_patient_reply(
        _case(),
        {"disclosed_slots": [], "messages": [], "variant_id": "default"},
        "有没有恶心出汗？",
    ))

    assert result["reply_mode"] == "slot_rule"
    assert result["matched_slots"] == ["accompanying"]
    assert len(result["matched_slots"]) == len(set(result["matched_slots"]))
    assert result["content"].count("没有特别的其他不舒服") == 1


def test_llm_prompt_is_grounded_to_allowed_slot_facts(monkeypatch):
    monkeypatch.setenv("TRIAGE_USE_LLM", "true")

    captured = {}

    async def fake_call_llm(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "大概就是刚才搬东西后开始疼的。"

    monkeypatch.setattr("services.triage_llm_patient.call_llm", fake_call_llm)

    from services.triage_patient_dialogue import generate_triage_patient_reply

    result = asyncio.run(generate_triage_patient_reply(
        _case(),
        {"disclosed_slots": [], "messages": [], "variant_id": "default"},
        "什么时候开始疼的？",
    ))

    assert result["reply_mode"] == "slot_llm"
    assert result["matched_slots"] == ["onset_time"]
    assert result["content"] == "大概就是刚才搬东西后开始疼的。"

    system_prompt = captured["messages"][0]["content"]
    assert "【已允许披露的信息】" in system_prompt
    assert "【受控事实包规则】" in system_prompt
    assert "起病时间" in system_prompt
    assert "刚才" in system_prompt
    allowed_info = system_prompt.rsplit("【已允许披露的信息】", 1)[1].split("【受控事实包规则】", 1)[0]
    assert "standard_answer" not in allowed_info
    assert "Ⅳ级" not in allowed_info
    assert "绿区" not in allowed_info
    assert "根据病例资料回答" not in allowed_info
    assert captured["kwargs"]["temperature"] == 0.45
