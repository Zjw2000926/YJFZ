from fastapi.testclient import TestClient

from main import app
from services.case_validator import validate_case
from services.triage_repository import get_case, list_cases


L2 = "\u2161\u7ea7"
L3 = "\u2162\u7ea7"
L4 = "\u2163\u7ea7"
RED = "\u7ea2\u533a"
YELLOW = "\u9ec4\u533a"
GREEN = "\u7eff\u533a"


def _headers(client: TestClient):
    response = client.post("/api/auth/login", json={"username": "student1", "password": "123456"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _start(client: TestClient, headers: dict, case_id: str, mode: str = "practice") -> str:
    response = client.post("/api/triage/training/start", json={"case_external_id": case_id, "mode": mode}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["record_id"]


def test_case_validator_accepts_current_case_library():
    invalid = []
    for item in list_cases(include_draft=True):
        result = validate_case(get_case(item["external_id"]))
        if result["errors"]:
            invalid.append((item["external_id"], result["errors"]))
    assert not invalid


def test_dynamic_mvp_case_validator_is_strictly_valid():
    result = validate_case(get_case("TRIAGE-DYN-RLQ-001"))
    assert result["valid"]
    assert result["case_type"] == "dynamic"
    assert result["errors"] == []


def test_static_chest_case_scores_and_iv_is_serious_error():
    with TestClient(app) as client:
        headers = _headers(client)

        correct_id = _start(client, headers, "TRIAGE-STATIC-CHEST-II-001")
        client.post(
            f"/api/triage/training/{correct_id}/measure",
            json={"measurement_ids": ["temperature", "heart_rate", "respiratory_rate", "blood_pressure", "spo2", "pain_score", "consciousness"]},
            headers=headers,
        )
        correct = client.post(
            f"/api/triage/training/{correct_id}/submit",
            json={"level": L2, "zone": RED, "disposition": ["notify_doctor"]},
            headers=headers,
        )
        assert correct.status_code == 200
        assert correct.json()["score"]["pass_status"] in ("pass", "good", "excellent")

        wrong_id = _start(client, headers, "TRIAGE-STATIC-CHEST-II-001")
        client.post(
            f"/api/triage/training/{wrong_id}/measure",
            json={"measurement_ids": ["temperature", "heart_rate", "respiratory_rate", "blood_pressure", "spo2", "pain_score", "consciousness"]},
            headers=headers,
        )
        wrong = client.post(
            f"/api/triage/training/{wrong_id}/submit",
            json={"level": L4, "zone": GREEN, "disposition": []},
            headers=headers,
        )
        assert wrong.status_code == 200
        score = wrong.json()["score"]
        assert score["severe_error_triggered"]
        assert score["pass_status"] == "fail"


def test_dynamic_correct_flow_reaches_completed_and_structured_report():
    with TestClient(app) as client:
        headers = _headers(client)
        rid = _start(client, headers, "TRIAGE-DYN-RLQ-001")
        client.post(f"/api/triage/training/{rid}/observe", json={"observation_ids": ["appearance"]}, headers=headers)
        client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate", "blood_pressure", "pain_score"]}, headers=headers)
        client.post(f"/api/triage/training/{rid}/initial-decision", json={"level": L3, "zone": YELLOW, "reassessment_minutes": 30}, headers=headers)
        client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 15}, headers=headers)
        client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate", "blood_pressure", "pain_score"]}, headers=headers)
        client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 15}, headers=headers)
        client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate", "blood_pressure", "pain_score"]}, headers=headers)
        client.post(f"/api/triage/training/{rid}/reassess", json={"selected_level": L2, "selected_zone": RED, "notify_doctor": True}, headers=headers)
        client.post(f"/api/triage/training/{rid}/notify-doctor", json={"reason": "deterioration"}, headers=headers)
        client.post(f"/api/triage/training/{rid}/save-notes", json={"content": "T30 reassessment and upgrade recorded"}, headers=headers)
        submitted = client.post(f"/api/triage/training/{rid}/submit", json={"level": L2, "zone": RED, "disposition": ["notify_doctor"]}, headers=headers)
        assert submitted.status_code == 200

        record = client.get(f"/api/triage/training/records/{rid}", headers=headers).json()["record"]
        assert record["timeline_state"]["current_stage"] == "COMPLETED"
        report = submitted.json()["score"]["timeline_report"]
        for key in [
            "case_info",
            "student_info",
            "training_mode",
            "score_breakdown",
            "action_timeline",
            "vital_sign_timeline",
            "serious_error_summary",
            "stage_history",
            "recommended_training",
        ]:
            assert key in report
        assert report["triage_upgraded"] is True
        assert report["doctor_notified"] is True

