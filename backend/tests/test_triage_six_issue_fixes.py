# -*- coding: utf-8 -*-
import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ["TRIAGE_USE_LLM"] = "false"

from main import app
from services.case_validator import validate_case
from services.triage_patient_dialogue import generate_triage_patient_reply
from services.triage_repository import get_case


L2 = "\u2161\u7ea7"
L3 = "\u2162\u7ea7"
RED = "\u7ea2\u533a"
YELLOW = "\u9ec4\u533a"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def headers(client):
    response = client.post("/api/auth/login", json={"username": "student1", "password": "123456"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _start(client, headers, case_id="TRIAGE-DYN-RLQ-001", mode="practice"):
    response = client.post(
        "/api/triage/training/start",
        json={"case_external_id": case_id, "mode": mode},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["record_id"]


def _measure_values(client, headers, record_id, ids):
    response = client.post(
        f"/api/triage/training/{record_id}/measure",
        json={"measurement_ids": ids},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return {item["id"]: str(item["value"]) for item in response.json()["measurements"]}


def _run(coro):
    return asyncio.run(coro)


def _patch_patient_llm(monkeypatch):
    async def fake_call_llm(messages, **kwargs):
        prompt = messages[-1]["content"]
        if "\u5934\u6655" in prompt or "\u5750\u5f97\u4f4f" in prompt:
            return "\u6211\u73b0\u5728\u5934\u6655\uff0c\u75bc\u5f97\u5750\u4e0d\u4f4f\uff0c\u8eab\u4e0a\u8fd8\u6709\u70b9\u5192\u51b7\u6c57\u3002"
        if "\u80f8" in prompt or "\u642c" in prompt:
            return "\u4e0d\u662f\u88ab\u4e1c\u897f\u649e\u5230\uff0c\u6211\u8bb0\u5f97\u662f\u642c\u4e1c\u897f\u540e\u80f8\u53e3\u8fd9\u8fb9\u523a\u75db\uff0c\u6309\u7740\u66f4\u75db\u3002"
        return "\u55ef\uff0c\u6211\u73b0\u5728\u5c31\u662f\u8fd9\u91cc\u4e0d\u592a\u8212\u670d\uff0c\u6709\u70b9\u62c5\u5fc3\u3002"

    monkeypatch.setattr("services.triage_patient_dialogue.call_llm", fake_call_llm)


def test_patient_dialogue_naturalizes_subjective_and_trigger_questions():
    async def _case():
        case = get_case("TRIAGE-DYN-RLQ-001")
        record = {
            "id": "dialogue-natural",
            "case_external_id": "TRIAGE-DYN-RLQ-001",
            "messages": [],
            "disclosed_slots": [],
            "variant_id": "default",
        }
        questions = [
            "\u73b0\u5728\u611f\u89c9\u600e\u4e48\u6837\uff1f",
            "\u4ec0\u4e48\u539f\u56e0\u5f15\u8d77\u4f60\u75bc\u7684\uff1f",
            "\u6709\u6ca1\u6709\u4ec0\u4e48\u8bf1\u56e0\uff1f",
            "\u4f60\u89c9\u5f97\u662f\u4e0d\u662f\u5403\u574f\u4e1c\u897f\u4e86\uff1f",
            "\u4f60\u4e3a\u4ec0\u4e48\u73b0\u5728\u624d\u6765\u533b\u9662\uff1f",
            "\u4f60\u4ee5\u524d\u6709\u8fc7\u8fd9\u79cd\u60c5\u51b5\u5417\uff1f",
        ]
        banned = ["\u95ee\u533b\u751f", "\u75c5\u4f8b\u4fe1\u606f", "\u7cfb\u7edf\u672a\u63d0\u4f9b", "\u65e0\u6cd5\u56de\u7b54", "\u6211\u8bf4\u4e0d\u592a\u51c6"]
        replies = []
        for question in questions:
            result = await generate_triage_patient_reply(case, record, question)
            replies.append(result)
            assert result["content"].strip()
            assert not any(term in result["content"] for term in banned), result
        assert replies[1]["reply_mode"] == "trigger_policy"
        assert replies[0]["reply_mode"] in {"subjective_policy", "slot_rule", "slot_llm"}

    _run(_case())


def test_static_chest_wall_pain_answers_mechanical_trigger_questions_naturally():
    async def _case():
        case = get_case("TRIAGE-006")
        banned = ["\u95ee\u533b\u751f", "\u75c5\u4f8b\u4fe1\u606f", "\u7cfb\u7edf\u672a\u63d0\u4f9b", "\u65e0\u6cd5\u56de\u7b54", "\u6211\u8bf4\u4e0d\u592a\u51c6"]

        collision_record = {"messages": [], "disclosed_slots": [], "variant_id": "default"}
        collision = await generate_triage_patient_reply(
            case,
            collision_record,
            "\u80f8\u53e3\u662f\u88ab\u4e1c\u897f\u649e\u51fb\u540e\u51fa\u73b0\u75bc\u75db\u7684\u5417",
        )
        assert collision["reply_mode"] == "mechanical_trigger_policy"
        assert "\u4e0d\u662f" in collision["content"]
        assert "\u642c" in collision["content"]
        assert not any(term in collision["content"] for term in banned), collision

        lifting_record = {"messages": [], "disclosed_slots": [], "variant_id": "default"}
        lifting = await generate_triage_patient_reply(
            case,
            lifting_record,
            "\u662f\u642c\u4e1c\u897f\u8fc7\u7a0b\u4e2d\u7a81\u7136\u51fa\u73b0\u75bc\u75db\u7684\u5417",
        )
        assert lifting["reply_mode"] == "mechanical_trigger_policy"
        assert "\u5bf9" in lifting["content"]
        assert "\u642c" in lifting["content"]
        assert not any(term in lifting["content"] for term in banned), lifting

    _run(_case())


def test_dynamic_validator_marks_stroke_and_pediatric_cases_as_vital_changing():
    for case_id in ["TRIAGE-008", "TRIAGE-039"]:
        result = validate_case(get_case(case_id))
        assert result["valid"], result
        profile = result["dynamic_profile"]
        assert profile["timeline_node_count"] >= 2
        assert profile["has_vital_change"] is True
        assert profile["dynamic_subtype"] in {"deterioration", "stable_reassessment"}


def test_stroke_dynamic_vitals_change_by_timeline(client, headers):
    record_id = _start(client, headers, "TRIAGE-008")
    t0 = _measure_values(client, headers, record_id, ["heart_rate", "blood_pressure", "spo2", "gcs_score"])

    client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 5}, headers=headers)
    t5 = _measure_values(client, headers, record_id, ["heart_rate", "blood_pressure", "spo2", "gcs_score"])

    client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 5}, headers=headers)
    t10 = _measure_values(client, headers, record_id, ["heart_rate", "blood_pressure", "spo2", "gcs_score"])

    assert t0["heart_rate"] != t5["heart_rate"] != t10["heart_rate"]
    assert t0["blood_pressure"] != t5["blood_pressure"] != t10["blood_pressure"]
    assert t10["gcs_score"] == "9"


def test_pediatric_dynamic_vitals_change_by_timeline(client, headers):
    record_id = _start(client, headers, "TRIAGE-039")
    t0 = _measure_values(client, headers, record_id, ["temperature", "heart_rate", "spo2", "blood_pressure"])

    client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 4}, headers=headers)
    t4 = _measure_values(client, headers, record_id, ["temperature", "heart_rate", "spo2", "blood_pressure"])

    client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 3}, headers=headers)
    t7 = _measure_values(client, headers, record_id, ["temperature", "heart_rate", "spo2", "blood_pressure"])

    assert t0["temperature"] != t4["temperature"] != t7["temperature"]
    assert t0["heart_rate"] != t4["heart_rate"] != t7["heart_rate"]
    assert t7["spo2"] == "88"


def test_reassessment_completeness_uses_actual_measurement_log(client, headers):
    record_id = _start(client, headers, "TRIAGE-DYN-RLQ-001")
    client.post(
        f"/api/triage/training/{record_id}/initial-decision",
        json={"level": L3, "zone": YELLOW, "reassessment_minutes": 30},
        headers=headers,
    )
    client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 30}, headers=headers)
    _measure_values(client, headers, record_id, ["heart_rate", "blood_pressure", "pain_score", "respiratory_rate", "spo2"])

    response = client.post(
        f"/api/triage/training/{record_id}/reassess",
        json={"selected_level": L2, "selected_zone": RED, "notify_doctor": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["completeness"] >= 0.99

    client.post(f"/api/triage/training/{record_id}/notify-doctor", json={"reason": "deterioration"}, headers=headers)
    submitted = client.post(
        f"/api/triage/training/{record_id}/submit",
        json={"level": L2, "zone": RED, "disposition": ["notify_doctor"]},
        headers=headers,
    )
    assert submitted.status_code == 200, submitted.text
    detail = submitted.json()["score"]["detail_scores"]
    assert detail["复评内容完成"]["score"] == 10


def test_timeline_advance_returns_state_snapshot(client, headers):
    record_id = _start(client, headers, "TRIAGE-DYN-RLQ-001")
    response = client.post(
        f"/api/triage/training/{record_id}/timeline/advance",
        json={"minutes": 15},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["current_minute"] == 15
    assert data["current_stage"]
    assert isinstance(data["patient_state"], dict)
    assert data["patient_state"].get("state_id")
    assert isinstance(data["visible_events"], list)
    assert isinstance(data["due_events"], list)


def test_training_report_suggestions_hide_internal_prompt_terms(client, headers):
    record_id = _start(client, headers, "TRIAGE-DYN-RLQ-001")
    client.post(f"/api/triage/training/{record_id}/observe", json={"observation_ids": ["appearance"]}, headers=headers)
    client.post(f"/api/triage/training/{record_id}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
    client.post(
        f"/api/triage/training/{record_id}/initial-decision",
        json={"level": L3, "zone": YELLOW, "reassessment_minutes": 30},
        headers=headers,
    )
    client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 30}, headers=headers)
    client.post(
        f"/api/triage/training/{record_id}/reassess",
        json={"selected_level": L2, "selected_zone": RED, "notify_doctor": True},
        headers=headers,
    )
    client.post(f"/api/triage/training/{record_id}/notify-doctor", json={"reason": "deterioration"}, headers=headers)
    response = client.post(
        f"/api/triage/training/{record_id}/submit",
        json={"level": L2, "zone": RED, "disposition": ["notify_doctor"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()["score"]["timeline_report"]
    text = "\n".join(report.get("improvement_suggestions", []) + report.get("recommended_training", []))
    blocked_terms = ["LLM", "token", "\u63d0\u793a\u8bcd", "\u8f93\u51fa\u9650\u5236", "\u4e0d\u5199\u6cbb\u7597\u5904\u65b9"]
    assert not any(term in text for term in blocked_terms), text


def test_current_state_question_after_t30_uses_dynamic_patient_state(client, headers, monkeypatch):
    _patch_patient_llm(monkeypatch)
    record_id = _start(client, headers, "TRIAGE-DYN-RLQ-001")
    client.post(
        f"/api/triage/training/{record_id}/initial-decision",
        json={"level": L3, "zone": YELLOW, "reassessment_minutes": 30},
        headers=headers,
    )
    client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 30}, headers=headers)

    response = client.post(
        f"/api/triage/training/{record_id}/message",
        json={"content": "\u73b0\u5728\u5934\u6655\u5417\uff0c\u8fd8\u80fd\u5750\u5f97\u4f4f\u5417\uff1f"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    reply = data["reply"]
    banned = ["\u95ee\u533b\u751f", "\u75c5\u4f8b\u4fe1\u606f", "\u7cfb\u7edf\u672a\u63d0\u4f9b", "\u65e0\u6cd5\u56de\u7b54", "\u6211\u8bf4\u4e0d\u592a\u51c6"]
    expected_terms = ["\u5934\u6655", "\u5750\u4e0d\u4f4f", "\u51b7\u6c57", "\u82cd\u767d", "\u75bc\u5f97", "\u96be\u53d7"]
    assert data["reply_mode"] == "current_state_policy_llm_api"
    assert data["llm_called"] is True
    assert not any(term in reply for term in banned), reply
    assert any(term in reply for term in expected_terms), reply


def test_stroke_dynamic_report_recognizes_non_deterioration_named_worsening_event(client, headers):
    record_id = _start(client, headers, "TRIAGE-008")
    client.post(
        f"/api/triage/training/{record_id}/initial-decision",
        json={"level": L2, "zone": RED, "reassessment_minutes": 10},
        headers=headers,
    )
    client.post(f"/api/triage/training/{record_id}/timeline/advance", json={"minutes": 10}, headers=headers)
    _measure_values(client, headers, record_id, ["gcs_score", "spo2", "heart_rate", "blood_pressure"])
    client.post(
        f"/api/triage/training/{record_id}/reassess",
        json={"selected_level": "\u2160\u7ea7", "selected_zone": RED, "notify_doctor": True},
        headers=headers,
    )
    client.post(f"/api/triage/training/{record_id}/notify-doctor", json={"reason": "GCS drop"}, headers=headers)

    response = client.post(
        f"/api/triage/training/{record_id}/submit",
        json={"level": "\u2160\u7ea7", "zone": RED, "disposition": ["notify_doctor"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()["score"]["timeline_report"]
    assert report["deterioration_recognized"] is True, report
    assert report["triage_upgraded"] is True, report
    assert report["doctor_notified"] is True, report


def test_static_chest_process_evidence_improves_feedback_explainability(client, headers, monkeypatch):
    _patch_patient_llm(monkeypatch)
    record_id = _start(client, headers, "TRIAGE-STATIC-CHEST-II-001")
    questions = [
        "\u4ec0\u4e48\u65f6\u5019\u5f00\u59cb\u80f8\u75db\u7684\uff1f",
        "\u80f8\u75db\u662f\u4ec0\u4e48\u611f\u89c9\uff0c\u6709\u6ca1\u6709\u653e\u5c04\u5230\u5de6\u80a9\u5de6\u81c2\uff1f",
        "\u6709\u6ca1\u6709\u51b7\u6c57\u3001\u6076\u5fc3\u6216\u6c14\u77ed\uff1f",
        "\u4ee5\u524d\u6709\u9ad8\u8840\u538b\u6216\u5fc3\u810f\u75c5\u53f2\u5417\uff1f",
    ]
    for question in questions:
        response = client.post(
            f"/api/triage/training/{record_id}/message",
            json={"content": question},
            headers=headers,
        )
        assert response.status_code == 200, response.text
    client.post(
        f"/api/triage/training/{record_id}/measure",
        json={"measurement_ids": ["temperature", "heart_rate", "respiratory_rate", "blood_pressure", "spo2", "pain_score"]},
        headers=headers,
    )
    response = client.post(
        f"/api/triage/training/{record_id}/submit",
        json={"level": L2, "zone": RED, "disposition": ["notify_doctor", "chest_pain_priority", "monitor", "reassess"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    feedback = response.json()["score"]["feedback"]
    process = feedback.get("process_evidence") or {}
    assert process.get("student_question_count", 0) >= 4, process
    assert process.get("intent_event_count", 0) >= 3, process
    assert "missed_required_questions" in feedback
