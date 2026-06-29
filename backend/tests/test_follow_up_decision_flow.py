from fastapi.testclient import TestClient

from main import app
from services.triage_follow_up import record_follow_up_decision, score_follow_up_decisions


L2 = "\u2161\u7ea7"
YELLOW = "\u9ec4\u533a"


def _headers(client: TestClient):
    response = client.post("/api/auth/login", json={"username": "student1", "password": "123456"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _start(client: TestClient, headers: dict, case_id: str = "TRIAGE-002") -> str:
    response = client.post(
        "/api/triage/training/start",
        json={"case_external_id": case_id, "mode": "practice"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["record_id"]


def test_follow_up_decision_required_case_complete_without_reassessment_is_serious():
    with TestClient(app) as client:
        headers = _headers(client)
        record_id = _start(client, headers)
        client.post(
            f"/api/triage/training/{record_id}/initial-decision",
            json={"level": L2, "zone": "\u4e13\u75c5\u7eff\u8272\u901a\u9053"},
            headers=headers,
        )
        decision = client.post(
            f"/api/triage/training/{record_id}/follow-up-decision",
            json={"selected_option": "complete_no_reassessment"},
            headers=headers,
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["decision"]["whether_correct"] is False

        submitted = client.post(
            f"/api/triage/training/{record_id}/submit",
            json={"level": L2, "zone": "\u4e13\u75c5\u7eff\u8272\u901a\u9053", "disposition": []},
            headers=headers,
        )
        assert submitted.status_code == 200, submitted.text
        score = submitted.json()["score"]
        assert score["serious_error_triggered"] is True
        assert "MISSED_REQUIRED_FOLLOW_UP" in score["serious_error_codes"]


def test_follow_up_reassessment_choice_advances_backend_state_only_after_student_decision():
    with TestClient(app) as client:
        headers = _headers(client)
        record_id = _start(client, headers)
        client.post(
            f"/api/triage/training/{record_id}/initial-decision",
            json={"level": L2, "zone": "\u4e13\u75c5\u7eff\u8272\u901a\u9053"},
            headers=headers,
        )
        response = client.post(
            f"/api/triage/training/{record_id}/follow-up-decision",
            json={"selected_option": "reassess_10"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["decision"]["whether_correct"] is True
        assert data["state_update"]
        assert data["state_update"]["title"] == "\u5019\u8bca\u89c2\u5bdf\u540e\u60a3\u8005\u72b6\u6001"
        assert "\u80f8\u75db\u52a0\u91cd" in data["state_update"]["expression"]
        assert data["show_decision_panel"] is True


def test_stable_case_over_reassessment_is_light_deduction_not_critical():
    case = {
        "external_id": "stable-demo",
        "standard_answer": {"triage_level": "\u2163\u7ea7", "triage_zone": "\u7eff\u533a"},
    }
    record = {"follow_up_decisions": [], "student_actions": []}
    result = record_follow_up_decision(record, case, {"selected_option": "reassess_30"})
    assert result["decision"]["whether_correct"] is False

    scored = score_follow_up_decisions(record, case)
    assert scored["score"] < scored["max"]
    assert "OVER_REASSESSMENT" in scored["issue_codes"]
    assert not any(item["critical_fail"] for item in scored["serious_errors"])
