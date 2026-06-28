from fastapi.testclient import TestClient

from main import app
from services.scoring_engine import score_case
from services.triage_repository import _save_record, get_record
from services.triage_repository import get_case


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


def test_static_score_dimensions_include_clickable_criteria_and_persist():
    with TestClient(app) as client:
        headers = _headers(client)
        rid = _start(client, headers, "TRIAGE-STATIC-CHEST-II-001")
        client.post(
            f"/api/triage/training/{rid}/measure",
            json={"measurement_ids": ["temperature", "heart_rate"]},
            headers=headers,
        )
        submitted = client.post(
            f"/api/triage/training/{rid}/submit",
            json={"level": L4, "zone": GREEN, "disposition": []},
            headers=headers,
        )
        assert submitted.status_code == 200, submitted.text
        score = submitted.json()["score"]
        detail = score["detail_scores"]

        assert detail
        assert all(dim.get("criteria") for dim in detail.values())
        assert any(dim.get("deduction_reasons") for dim in detail.values())
        assert any("standard_basis" in dim for dim in detail.values())
        assert any("international_reference" in dim for dim in detail.values())

        persisted = client.get(f"/api/triage/training/records/{rid}", headers=headers).json()["record"]
        persisted_detail = persisted["score_detail"]
        assert all(dim.get("criteria") for dim in persisted_detail.values())
        assert persisted.get("score_explanations")


def test_dynamic_reassessment_omissions_have_explicit_deduction_reasons():
    with TestClient(app) as client:
        headers = _headers(client)
        rid = _start(client, headers, "TRIAGE-DYN-RLQ-001")
        client.post(f"/api/triage/training/{rid}/observe", json={"observation_ids": ["appearance"]}, headers=headers)
        client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
        client.post(f"/api/triage/training/{rid}/initial-decision", json={"level": L3, "zone": YELLOW}, headers=headers)
        client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)
        submitted = client.post(
            f"/api/triage/training/{rid}/submit",
            json={"level": L3, "zone": YELLOW, "disposition": []},
            headers=headers,
        )
        assert submitted.status_code == 200, submitted.text
        detail = submitted.json()["score"]["detail_scores"]

        joined_reasons = " ".join(
            reason
            for dim in detail.values()
            for reason in (dim.get("deduction_reasons") or [])
        )
        assert "复评" in joined_reasons
        assert "通知医生" in joined_reasons or "升级分诊" in joined_reasons
        assert any(dim.get("criteria") for name, dim in detail.items() if "复评" in name or "变化" in name)


def test_old_record_detail_backfills_score_explanations():
    with TestClient(app) as client:
        headers = _headers(client)
        rid = _start(client, headers, "TRIAGE-STATIC-CHEST-II-001")
        submitted = client.post(
            f"/api/triage/training/{rid}/submit",
            json={"level": L4, "zone": GREEN, "disposition": []},
            headers=headers,
        )
        assert submitted.status_code == 200, submitted.text

        record = get_record(rid)
        assert record
        legacy_detail = {}
        for name, dim in (record.get("score_detail") or {}).items():
            legacy_detail[name] = {"score": dim.get("score"), "max": dim.get("max")}
        record["score_detail"] = legacy_detail
        record["score_explanations"] = []
        record["criterion_scores"] = []
        _save_record(record)

        detail_response = client.get(f"/api/triage/training/records/{rid}", headers=headers)
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()["record"]["score_detail"]
        assert all(dim.get("criteria") for dim in detail.values())
        assert detail_response.json()["record"]["score_explanations"]


def test_score_explanation_normalizes_vital_aliases_and_stays_score_consistent():
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
            json={
                "level": "\u2160\u7ea7",
                "zone": RED,
                "disposition": ["通知医生"],
                "reason": "胸痛伴冷汗、疼痛重，存在高危信号。",
                "note": "已通知医生，安排红区优先处置并持续观察。",
            },
            headers=headers,
        )
        assert submitted.status_code == 200, submitted.text
        detail = submitted.json()["score"]["detail_scores"]

        for dim in detail.values():
            criteria = dim.get("criteria") or []
            assert round(sum(float(c.get("score", 0)) for c in criteria), 2) == round(float(dim["score"]), 2)
            assert round(sum(float(c.get("max", 0)) for c in criteria), 2) == round(float(dim["max"]), 2)
            assert all(not c.get("improvement") for c in criteria if c.get("status") == "complete")

        vitals_dim = next(dim for dim in detail.values() if dim.get("dimension_id") == "vitals")
        vitals_text = " ".join(
            (c.get("deduction_reason") or "") + " " + (c.get("evidence") or "")
            for c in vitals_dim.get("criteria", [])
        )
        assert "缺少: 心率" not in vitals_text
        assert "缺少: 呼吸" not in vitals_text
        assert "缺少: SpO2" not in vitals_text
        assert "dynamic_recheck" not in {c.get("id") for c in vitals_dim.get("criteria", [])}

        disposition_dim = next(dim for dim in detail.values() if dim.get("dimension_id") == "disposition")
        notify_item = next(c for c in disposition_dim["criteria"] if c.get("id") == "notify")
        assert notify_item["score"] > 0
        assert not notify_item.get("deduction_reason")

        record = submitted.json()["record"]
        assert record["triage_reason"]
        assert record["notes"]


def _history_dimension(score: dict):
    return next(dim for dim in score["detail_scores"].values() if dim.get("dimension_id") == "history")


def test_history_score_requires_category_coverage_not_question_count_only():
    case = get_case("TRIAGE-001")
    record = {
        "id": "history-too-short",
        "case_external_id": "TRIAGE-001",
        "disclosed_slots": ["slot_001", "slot_002", "chief_complaint", "onset_time"],
        "intent_events": [
            {"intent": "ask_chief_complaint"},
            {"intent": "ask_onset_time"},
            {"intent": "ask_pain_location"},
        ],
        "messages": [
            {"role": "student", "content": "你哪里不舒服？"},
            {"role": "patient", "content": "胸口压得厉害，喘不上气。"},
            {"role": "student", "content": "具体多久了？"},
            {"role": "patient", "content": "刚才开始，大概十来分钟。"},
            {"role": "student", "content": "胸口具体哪个部位？"},
            {"role": "patient", "content": "就是胸口这一片。"},
        ],
        "measured_vitals": ["blood_pressure", "heart_rate_bpm", "respiratory_rate_bpm", "spo2_percent", "pain_score", "consciousness"],
        "final_level_selected": "\u2160\u7ea7",
        "final_zone_selected": RED,
        "final_disposition": ["通知医生"],
        "triage_reason": "胸痛伴气促，先按高危处理。",
    }

    score = score_case(record, case)
    history = _history_dimension(score)
    assoc = next(c for c in history["criteria"] if c["id"] == "associated_history")
    change = next(c for c in history["criteria"] if c["id"] == "change_trend")

    assert history["score"] < history["max"]
    assert assoc["score"] < assoc["max"]
    assert change["score"] < change["max"]
    reasons = " ".join(history.get("deduction_reasons") or [])
    assert "既往史" in reasons
    assert "用药史" in reasons
    assert "过敏史" in reasons


def test_history_score_allows_high_score_when_required_categories_are_covered():
    case = get_case("TRIAGE-001")
    record = {
        "id": "history-complete",
        "case_external_id": "TRIAGE-001",
        "disclosed_slots": [],
        "intent_events": [],
        "messages": [
            {"role": "student", "content": "你哪里不舒服？"},
            {"role": "patient", "content": "胸口压得特别厉害，喘不上气。"},
            {"role": "student", "content": "什么时候开始，疼痛性质和部位怎么样？"},
            {"role": "patient", "content": "刚才开始十来分钟，胸口这一片像石头压着，很难受。"},
            {"role": "student", "content": "有没有放射痛、出汗、恶心、晕厥或气促？"},
            {"role": "patient", "content": "没有往肩背放射，但出了冷汗，喘不上气，差点晕过去。"},
            {"role": "student", "content": "既往有心脏病、高血压、糖尿病、吸烟史吗？"},
            {"role": "patient", "content": "有高血压和糖尿病，平时也抽烟。"},
            {"role": "student", "content": "平时吃什么药，最近控制稳定吗？有没有药物过敏？"},
            {"role": "patient", "content": "吃降压药和降糖药，最近控制不稳定，没有发现药物过敏。"},
            {"role": "student", "content": "以前有过类似发作吗？这次有没有加重或变化？"},
            {"role": "patient", "content": "以前没有这么严重过，这次突然发作，越来越难受。"},
        ],
        "measured_vitals": ["blood_pressure", "heart_rate_bpm", "respiratory_rate_bpm", "spo2_percent", "pain_score", "consciousness"],
        "final_level_selected": "\u2160\u7ea7",
        "final_zone_selected": RED,
        "final_disposition": ["通知医生"],
        "triage_reason": "胸痛伴冷汗、气促和危险因素，立即红区通知医生。",
    }

    score = score_case(record, case)
    history = _history_dimension(score)
    assert history["score"] >= history["max"] * 0.9
    assert not history.get("deduction_reasons")
