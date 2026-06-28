from fastapi.testclient import TestClient

from main import app
from services.triage_repository import list_cases


L1 = "\u2160\u7ea7"
L2 = "\u2161\u7ea7"
L3 = "\u2162\u7ea7"
RED = "\u7ea2\u533a"
YELLOW = "\u9ec4\u533a"


def _headers(client: TestClient):
    response = client.post("/api/auth/login", json={"username": "student1", "password": "123456"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _start(client: TestClient, headers: dict, case_id: str) -> str:
    response = client.post("/api/triage/training/start", json={"case_external_id": case_id, "mode": "practice"}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["record_id"]


def test_triage001_static_case_does_not_show_dynamic_reassessment_failures():
    """TRIAGE-001 is an immediate static case; report must not ask for waiting reassessment/upgrade."""
    with TestClient(app) as client:
        headers = _headers(client)
        rid = _start(client, headers, "TRIAGE-001")
        measure = client.post(
            f"/api/triage/training/{rid}/measure",
            json={"measurement_ids": ["blood_pressure", "heart_rate_bpm", "spo2_percent", "pain_score"]},
            headers=headers,
        )
        assert measure.status_code == 200, measure.text

        submitted = client.post(
            f"/api/triage/training/{rid}/submit",
            json={"level": L3, "zone": YELLOW, "disposition": []},
            headers=headers,
        )
        assert submitted.status_code == 200, submitted.text
        report = submitted.json()["score"]["timeline_report"]

        assert report["case_type"] == "static"
        assert report["is_dynamic_case"] is False
        assert report["reassessment_applicable"] is False
        assert report["deterioration_applicable"] is False
        assert report["upgrade_applicable"] is False
        assert report["reassessment_on_time"] is None
        assert report["deterioration_recognized"] is None
        assert report["triage_upgraded"] is None
        assert report["doctor_notification_required"] is True
        assert report["doctor_notified"] is False

        detail = submitted.json()["score"]["detail_scores"]
        safety = detail["候诊复评与安全管理"]
        assert safety["dimension_id"] == "safety_management"
        reasons = " ".join(safety.get("deduction_reasons") or [])
        assert "复评时间" not in reasons
        assert "未按复评" not in reasons
        assert "不候诊" in reasons or "红区" in reasons


def test_triage001_correct_static_flow_marks_doctor_notified_without_dynamic_flags():
    with TestClient(app) as client:
        headers = _headers(client)
        rid = _start(client, headers, "TRIAGE-001")
        client.post(
            f"/api/triage/training/{rid}/measure",
            json={"measurement_ids": ["blood_pressure", "heart_rate_bpm", "respiratory_rate_bpm", "spo2_percent", "pain_score", "consciousness"]},
            headers=headers,
        )
        submitted = client.post(
            f"/api/triage/training/{rid}/submit",
            json={"level": L1, "zone": RED, "disposition": ["notify_doctor"]},
            headers=headers,
        )
        assert submitted.status_code == 200, submitted.text
        report = submitted.json()["score"]["timeline_report"]
        assert report["is_dynamic_case"] is False
        assert report["reassessment_applicable"] is False
        assert report["upgrade_applicable"] is False
        assert report["doctor_notification_required"] is True
        assert report["doctor_notified"] is True


def test_case_list_dynamic_flag_matches_timeline_enabled():
    """A case with enabled dynamic_timeline must route to the dynamic training page."""
    items = list_cases(include_draft=True)
    mismatches = [
        item["external_id"]
        for item in items
        if item.get("dynamic_profile", {}).get("has_timeline") and not item.get("is_dynamic")
    ]
    assert mismatches == []
