import asyncio

from fastapi.testclient import TestClient

from main import app


def _headers(client: TestClient):
    response = client.post("/api/auth/login", json={"username": "student1", "password": "123456"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _start_dynamic(client: TestClient, headers: dict, mode: str = "practice") -> str:
    response = client.post(
        "/api/triage/training/start",
        json={"case_external_id": "TRIAGE-DYN-RLQ-001", "mode": mode},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["record_id"]


def _initial_triage(client: TestClient, headers: dict, record_id: str):
    response = client.post(
        f"/api/triage/training/{record_id}/initial-decision",
        json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30, "reason": "初始生命体征平稳但需候诊复评"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_practice_timeline_hides_future_answer_details():
    with TestClient(app) as client:
        headers = _headers(client)
        record_id = _start_dynamic(client, headers)

        response = client.get(f"/api/triage/training/{record_id}/timeline", headers=headers)
        assert response.status_code == 200
        events = response.json()["timeline_events"]
        future = [event for event in events if not event.get("triggered")]
        assert future
        forbidden_keys = {
            "expected_student_actions",
            "vital_changes",
            "standard_level_after_event",
            "severe_error_if_ignored",
            "severe_error_code",
            "consequence_if_missed",
        }
        for event in future:
            assert not forbidden_keys.intersection(event.keys())
            assert event.get("event_description") == "待观察"
            text = str(event)
            assert "升级为Ⅱ级" not in text
            assert "红区" not in text
            assert "HR 122" not in text


def test_due_event_cue_is_natural_not_answer_like():
    with TestClient(app) as client:
        headers = _headers(client)
        record_id = _start_dynamic(client, headers)
        _initial_triage(client, headers, record_id)

        response = client.post(
            f"/api/triage/training/{record_id}/timeline/advance",
            json={"minutes": 30},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        text = str(response.json().get("due_events", [])) + str(response.json().get("events", []))
        for leak in ["升级为Ⅱ级", "调整至红区", "必须立即", "严重错误", "expected_student_actions"]:
            assert leak not in text
        assert "候诊巡视" in text or "患者主动表示" in text


def test_t15_reassessment_uses_current_state_standard_not_global_rule():
    with TestClient(app) as client:
        headers = _headers(client)
        record_id = _start_dynamic(client, headers)
        _initial_triage(client, headers, record_id)
        client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 15}, headers=headers)
        client.post(
            f"/api/triage/training/{record_id}/measure",
            json={"measurement_ids": ["heart_rate", "blood_pressure", "pain_score", "respiratory_rate"]},
            headers=headers,
        )

        response = client.post(
            f"/api/triage/training/{record_id}/reassess",
            json={"selected_level": "Ⅲ级", "selected_zone": "黄区", "notify_doctor": True},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        rule = data["rule_result"]
        assert rule["final_standard_level"] == "Ⅲ级"
        assert rule["under_triage"] is False
        assert data["upgrade_needed"] is False


def test_t30_reassessment_requires_level_two_when_not_upgraded():
    with TestClient(app) as client:
        headers = _headers(client)
        record_id = _start_dynamic(client, headers)
        _initial_triage(client, headers, record_id)
        client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 30}, headers=headers)
        client.post(
            f"/api/triage/training/{record_id}/measure",
            json={"measurement_ids": ["heart_rate", "blood_pressure", "pain_score", "respiratory_rate"]},
            headers=headers,
        )

        response = client.post(
            f"/api/triage/training/{record_id}/reassess",
            json={"selected_level": "Ⅲ级", "selected_zone": "黄区", "notify_doctor": False},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["rule_result"]["final_standard_level"] == "Ⅱ级"
        assert data["rule_result"]["under_triage"] is True
        assert data["upgrade_needed"] is True


def test_dynamic_vital_interpretations_are_chinese():
    with TestClient(app) as client:
        headers = _headers(client)
        record_id = _start_dynamic(client, headers)
        _initial_triage(client, headers, record_id)
        client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 30}, headers=headers)

        response = client.post(
            f"/api/triage/training/{record_id}/measure",
            json={"measurement_ids": ["temperature", "heart_rate", "respiratory_rate", "blood_pressure", "pain_score"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        interpretations = " ".join(item.get("interpretation", "") for item in response.json()["measurements"])
        assert "Heart rate" not in interpretations
        assert "Fever may" not in interpretations
        assert "Blood pressure" not in interpretations
        assert "风险" in interpretations or "复评" in interpretations


def test_first_look_observation_uses_natural_defaults():
    with TestClient(app) as client:
        headers = _headers(client)
        record_id = _start_dynamic(client, headers)

        response = client.post(
            f"/api/triage/training/{record_id}/observe",
            json={"observation_ids": ["skin_perfusion", "consciousness"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        values = [item["value"] for item in response.json()["observations"]]
        assert all("未描述" not in value for value in values)
        assert any("皮肤灌注" in value or "冷汗" in value or "苍白" in value for value in values)


def test_current_symptom_questions_do_not_match_trauma_or_head_injury():
    from services.triage_intent import match_intent

    questions = [
        "我看到你有点坐不住，现在疼痛比刚才怎么样？有没有新的不舒服？",
        "你现在脸色发白出汗，头晕吗？疼痛几分？",
    ]
    for question in questions:
        ids = {item["intent_id"] for item in match_intent(question)}
        assert "ask_trauma_detail" not in ids
        assert "ask_head_injury" not in ids
        assert {"ask_aggravating_relieving", "ask_severity"} & ids

    history_ids = {item["intent_id"] for item in match_intent("以前有没有做过相关手术？")}
    assert "ask_past_history" in history_ids


def test_llm_output_guard_blocks_unsupported_medical_facts(monkeypatch):
    monkeypatch.setenv("TRIAGE_USE_LLM", "true")

    async def fake_call_llm(messages, **kwargs):
        return "以前做过一次阑尾手术，现在还有点头晕、冒冷汗。"

    monkeypatch.setattr("services.triage_llm_patient.call_llm", fake_call_llm)

    from services.triage_patient_dialogue import generate_triage_patient_reply
    from services.triage_repository import get_case

    case = get_case("TRIAGE-006")
    result = asyncio.run(generate_triage_patient_reply(
        case,
        {"disclosed_slots": [], "messages": [], "variant_id": "default"},
        "什么时候开始疼的？",
    ))
    assert "阑尾手术" not in result["content"]
    assert "冒冷汗" not in result["content"]
    assert "头晕" not in result["content"]
    assert any("unsupported_medical_fact" in item for item in result.get("violations", []))


def test_required_llm_api_reply_also_uses_fact_guard(monkeypatch):
    async def fake_call_llm(messages, **kwargs):
        return "没有什么病史，就是现在头晕、冒冷汗，感觉血压掉下来了。"

    monkeypatch.setattr("services.triage_patient_dialogue.call_llm", fake_call_llm)

    from services.triage_patient_dialogue import require_llm_patient_reply
    from services.triage_repository import get_case

    case = get_case("TRIAGE-DYN-RLQ-001")
    dialog_result = {
        "content": "没有高血压糖尿病，也没有明确相关手术史。",
        "reply_mode": "slot_rule",
        "matched_slots": ["past_history"],
        "question_type": "factual_question",
    }
    result = asyncio.run(require_llm_patient_reply(
        case,
        {"id": "guarded", "mode": "practice", "disclosed_slots": []},
        "以前有没有做过相关手术？",
        dialog_result,
    ))
    assert "头晕" not in result["content"]
    assert "冒冷汗" not in result["content"]
    assert "血压掉" not in result["content"]
    assert "手术史" in result["content"] or "高血压" in result["content"]
    assert any("unsupported_medical_fact" in item for item in result.get("llm_violations", []))
