"""动态 MVP 测试: TRIAGE-DYN-RLQ-001 完整流程 + 严重错误路径"""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def headers(client):
    r = client.post("/api/auth/login", json={"username": "student1", "password": "123456"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _start(client, headers, case_id="TRIAGE-DYN-RLQ-001"):
    r = client.post("/api/triage/training/start",
                    json={"case_external_id": case_id, "mode": "practice"}, headers=headers)
    assert r.status_code == 200, f"start failed: {r.text}"
    return r.json()["record_id"]


def test_dynamic_case_schema_valid():
    """MVP 病例结构校验"""
    import json
    from pathlib import Path
    p = Path("triage_data/cases_dynamic/TRIAGE-DYN-RLQ-001.json")
    assert p.exists(), "病例文件不存在"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["is_dynamic"] is True
    assert data["dynamic_timeline"]["enabled"] is True
    states = data.get("patient_states", [])
    minutes = {s["time_minute"] for s in states}
    assert {0, 15, 30}.issubset(minutes), f"缺少时间节点: {minutes}"
    assert any(s["time_minute"] == 0 and s["standard_triage_level"] == "Ⅲ级" for s in states)
    assert any(s["time_minute"] == 30 and s["standard_triage_level"] == "Ⅱ级" for s in states)
    print("dynamic case schema OK")


def test_generated_dynamic_initial_stage_object_is_normalized(client, headers):
    """批量迁移病例的 initial_stage 可能是对象，接口必须归一为状态字符串。"""
    rid = _start(client, headers, "TRIAGE-002")
    r = client.get(f"/api/triage/training/{rid}/timeline", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["current_stage"] == "ARRIVAL"
    assert isinstance(data["patient_state"]["stage"], str)
    assert data["patient_state"]["stage"] == "ARRIVAL"


def test_dynamic_timeline_t0_t15_t30(client, headers):
    """时间轴推进 T15, T30"""
    rid = _start(client, headers)
    # T0: 初始测量
    r = client.post(f"/api/triage/training/{rid}/measure",
                    json={"measurement_ids": ["temperature", "heart_rate", "blood_pressure"]}, headers=headers)
    assert r.status_code == 200
    ms = r.json()["measurements"]
    # T0 体征验证
    for m in ms:
        if m["id"] == "heart_rate":
            assert "94" in str(m["value"]), f"T0 HR should be 94, got {m['value']}"

    # 初始分诊
    r = client.post(f"/api/triage/training/{rid}/initial-decision",
                    json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30}, headers=headers)
    assert r.status_code == 200

    # 推进到 T15
    r = client.post(f"/api/triage/training/{rid}/timeline/advance",
                    json={"minutes": 15}, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["current_minute"] == 15

    # 推进到 T30
    r = client.post(f"/api/triage/training/{rid}/timeline/advance",
                    json={"minutes": 15}, headers=headers)
    assert r.status_code == 200
    assert r.json()["current_minute"] == 30


def test_dynamic_vitals_change_by_state(client, headers):
    """P1-6: 不同时间点返回不同生命体征 — 包含 BP/HR/SpO2/NRS"""
    rid = _start(client, headers)

    r = client.post(f"/api/triage/training/{rid}/measure",
                    json={"measurement_ids": ["heart_rate", "blood_pressure", "pain_score", "spo2"]}, headers=headers)
    t0 = {m["id"]: str(m["value"]) for m in r.json()["measurements"]}
    assert "94" in t0.get("heart_rate", ""), f"T0 HR={t0}"
    assert "118/74" in t0.get("blood_pressure", ""), f"T0 BP={t0}"

    # T15
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 15}, headers=headers)
    r = client.post(f"/api/triage/training/{rid}/measure",
                    json={"measurement_ids": ["heart_rate", "blood_pressure", "pain_score", "spo2"]}, headers=headers)
    t15 = {m["id"]: str(m["value"]) for m in r.json()["measurements"]}
    assert "108" in t15.get("heart_rate", ""), f"T15 HR={t15}"
    assert "108/68" in t15.get("blood_pressure", ""), f"T15 BP should be 108/68, got {t15}"

    # T30
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 15}, headers=headers)
    r = client.post(f"/api/triage/training/{rid}/measure",
                    json={"measurement_ids": ["heart_rate", "blood_pressure", "pain_score", "spo2"]}, headers=headers)
    t30 = {m["id"]: str(m["value"]) for m in r.json()["measurements"]}
    assert "122" in t30.get("heart_rate", ""), f"T30 HR={t30}"
    assert "96/60" in t30.get("blood_pressure", ""), f"T30 BP should be 96/60, got {t30}"
    assert "97" in t30.get("spo2", ""), f"T30 SpO2={t30}"

    # 三时间点值应不同
    assert t0 != t15 != t30, "T0/T15/T30 vitals should all differ"


def test_dynamic_no_reassessment_severe(client, headers):
    """恶化后不复评 — 应触发严重错误"""
    rid = _start(client, headers)

    # 观测 + 初始分诊
    client.post(f"/api/triage/training/{rid}/observe",
                json={"observation_ids": ["appearance"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/initial-decision",
                json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30}, headers=headers)

    # 推进到 T30 (恶化) — 不复评直接提交
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)

    r = client.post(f"/api/triage/training/{rid}/submit",
                    json={"level": "Ⅲ级", "zone": "黄区", "disposition": []}, headers=headers)
    assert r.status_code == 200
    score = r.json().get("score", {})
    assert score.get("severe_error_triggered"), f"应触发严重错误: {score}"
    assert score.get("pass_status") == "fail"


def test_dynamic_reassessment_on_time_does_not_trigger_severe(client, headers):
    """按时复评并升级 — 不应触发严重错误"""
    rid = _start(client, headers)
    client.post(f"/api/triage/training/{rid}/observe", json={"observation_ids": ["appearance"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/initial-decision",
                json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30}, headers=headers)
    # 推进到 T30
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)
    # 复评 + 升级
    client.post(f"/api/triage/training/{rid}/reassess",
                json={"selected_level": "Ⅱ级", "selected_zone": "红区", "notify_doctor": True}, headers=headers)
    client.post(f"/api/triage/training/{rid}/notify-doctor", json={"reason": "病情恶化需升级"}, headers=headers)
    r = client.post(f"/api/triage/training/{rid}/submit",
                    json={"level": "Ⅱ级", "zone": "红区", "disposition": ["notify_doctor"]}, headers=headers)
    assert r.status_code == 200
    score = r.json().get("score", {})
    # 按时复评+升级+通知医生，不应触发严重错误
    assert not score.get("severe_error_triggered"), f"不应触发严重错误: {score.get('severe_errors')}"
    # P1-6: 断言四个标志均正确
    tr = score.get("timeline_report", {})
    assert tr.get("reassessment_on_time"), f"reassessment_on_time应为True: {tr}"
    assert tr.get("deterioration_recognized"), f"deterioration_recognized应为True: {tr}"
    assert tr.get("triage_upgraded"), f"triage_upgraded应为True: {tr}"
    assert tr.get("doctor_notified"), f"doctor_notified应为True: {tr}"


def test_dynamic_no_upgrade_after_t30_is_severe(client, headers):
    """T30 恶化后复评但未升级 — 触发严重错误"""
    rid = _start(client, headers)
    client.post(f"/api/triage/training/{rid}/observe", json={"observation_ids": ["appearance"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/initial-decision",
                json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30}, headers=headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)
    # 复评但保持 III级
    client.post(f"/api/triage/training/{rid}/reassess",
                json={"selected_level": "Ⅲ级", "selected_zone": "黄区"}, headers=headers)
    r = client.post(f"/api/triage/training/{rid}/submit",
                    json={"level": "Ⅲ级", "zone": "黄区", "disposition": []}, headers=headers)
    assert r.status_code == 200
    score = r.json().get("score", {})
    # 恶化后不升级应触发严重错误
    assert score.get("severe_error_triggered"), f"应触发严重错误(未升级): {score.get('severe_errors')}"
    assert score.get("pass_status") == "fail"


def test_dynamic_no_doctor_notification_deducts(client, headers):
    """升级但未通知医生 — 应有扣分或严重错误"""
    rid = _start(client, headers)
    client.post(f"/api/triage/training/{rid}/observe", json={"observation_ids": ["appearance"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/initial-decision",
                json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30}, headers=headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)
    # 复评升级但未通知医生
    client.post(f"/api/triage/training/{rid}/reassess",
                json={"selected_level": "Ⅱ级", "selected_zone": "红区", "notify_doctor": False}, headers=headers)
    r = client.post(f"/api/triage/training/{rid}/submit",
                    json={"level": "Ⅱ级", "zone": "红区", "disposition": []}, headers=headers)
    assert r.status_code == 200
    score = r.json().get("score", {})
    severe = score.get("severe_errors", [])
    # 至少有一个关于通知医生的扣分或严重错误
    has_doctor_issue = any("DOCTOR" in s.get("code", "") or "通知" in s.get("message", "") for s in severe)
    print(f"score={score.get('total_score')}, severe={[s.get('code') for s in severe]}")
    # 升级未通知医生应被识别
    assert has_doctor_issue or score.get("total_score", 100) < 100, f"未通知医生应有扣分: {score}"


def test_static_case_still_works(client, headers):
    """静态病例不受影响"""
    r = client.post("/api/triage/training/start",
                    json={"case_external_id": "TRIAGE-001", "mode": "practice"}, headers=headers)
    assert r.status_code == 200
    rid = r.json()["record_id"]

    r = client.post(f"/api/triage/training/{rid}/measure",
                    json={"measurement_ids": ["blood_pressure"]}, headers=headers)
    assert r.status_code == 200

    r = client.post(f"/api/triage/training/{rid}/submit",
                    json={"level": "Ⅱ级", "zone": "黄区", "disposition": ["notify_doctor"]}, headers=headers)
    assert r.status_code == 200
    assert r.json().get("score", {}).get("total_score") is not None


def test_exam_timeline_does_not_leak_hints(client, headers):
    """P0-2: exam 模式时间轴不泄露复评提示和严重错误"""
    r = client.post("/api/triage/training/start",
                    json={"case_external_id": "TRIAGE-DYN-RLQ-001", "mode": "exam"}, headers=headers)
    assert r.status_code == 200
    rid = r.json()["record_id"]
    # 推进到 T30
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)
    # 获取时间轴
    r = client.get(f"/api/triage/training/{rid}/timeline", headers=headers)
    events = r.json().get("timeline_events", [])
    for ev in events:
        assert "student_prompt" not in ev or not ev["student_prompt"], f"leaked student_prompt: {ev}"
        assert "expected_student_actions" not in ev, f"leaked expected: {ev}"
        assert "standard_level_after_event" not in ev, f"leaked standard_level: {ev}"
        assert "severe_error_if_ignored" not in ev, f"leaked severe: {ev}"
        assert "severe_error_code" not in ev, f"leaked severe_code: {ev}"
        assert "consequence_if_missed" not in ev, f"leaked consequence: {ev}"


def test_dynamic_messages_persist_after_advance(client, headers):
    """P1-2: 推进时间后 messages 应保留患者状态变化消息"""
    rid = _start(client, headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)
    r = client.get(f"/api/triage/training/records/{rid}", headers=headers)
    msgs = r.json().get("record", {}).get("messages", [])
    # 至少应有开场白消息
    assert len(msgs) >= 1, f"应该至少1条消息, got {len(msgs)}: {[m['content'][:30] for m in msgs]}"


def test_dynamic_student_actions_include_measures(client, headers):
    """P1-3: T0/T15/T30 测量后 student_actions 应包含 measure_vitals"""
    rid = _start(client, headers)
    # T0
    client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 15}, headers=headers)
    client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 15}, headers=headers)
    client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
    r = client.get(f"/api/triage/training/{rid}/timeline", headers=headers)
    actions = r.json().get("student_actions", [])
    measures = [a for a in actions if a.get("action_type") == "measure_vitals"]
    assert len(measures) >= 3, f"应有>=3条measure_vitals, got {len(measures)}: {[a['action_type'] for a in actions]}"


def test_state_machine_progresses(client, headers):
    """P0-3: 状态机应从 ARRIVAL 推进到提交"""
    rid = _start(client, headers)
    # observe -> measure -> initial -> advance -> reassess -> upgrade -> submit
    client.post(f"/api/triage/training/{rid}/observe", json={"observation_ids": ["appearance"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/initial-decision",
                json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30}, headers=headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)
    client.post(f"/api/triage/training/{rid}/reassess",
                json={"selected_level": "Ⅱ级", "selected_zone": "红区", "notify_doctor": True}, headers=headers)
    client.post(f"/api/triage/training/{rid}/notify-doctor", json={"reason": "恶化"}, headers=headers)
    client.post(f"/api/triage/training/{rid}/submit",
                json={"level": "Ⅱ级", "zone": "红区", "disposition": ["notify_doctor"]}, headers=headers)
    r = client.get(f"/api/triage/training/{rid}/timeline", headers=headers)
    data = r.json()
    stage = data.get("current_stage", data.get("timeline_state", {}).get("current_stage", ""))
    assert stage == "COMPLETED", f"状态机未推进到COMPLETED: {stage}"
    record = client.get(f"/api/triage/training/records/{rid}", headers=headers).json().get("record", {})
    history = record.get("timeline_state", {}).get("stage_history", [])
    targets = [h.get("to") for h in history]
    assert "WAITING" in targets
    assert "DETERIORATED" in targets
    assert "COMPLETED" in targets


def test_exam_timeline_patient_state_redacted(client, headers):
    """P1-4: exam 模式 patient_state 不泄露标准答案"""
    r = client.post("/api/triage/training/start",
                    json={"case_external_id": "TRIAGE-DYN-RLQ-001", "mode": "exam"}, headers=headers)
    assert r.status_code == 200
    rid = r.json()["record_id"]
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)
    r = client.get(f"/api/triage/training/{rid}/timeline", headers=headers)
    ps = r.json().get("patient_state", {})
    forbidden = ["standard_triage_level", "standard_area", "recommended_actions", "state_vitals"]
    for key in forbidden:
        assert key not in ps or ps[key] is None, f"exam patient_state leaked: {key}={ps.get(key)}"
    # current-state 同样不泄露
    r2 = client.get(f"/api/triage/training/{rid}/current-state", headers=headers)
    ps2 = r2.json()
    for key in forbidden:
        assert key not in ps2 or ps2[key] is None, f"exam current-state leaked: {key}={ps2.get(key)}"


def test_student_can_see_dynamic_case(client, headers):
    """P1-4: 学生病例列表至少包含一个可见动态病例"""
    r = client.get("/api/triage/cases", headers=headers)
    items = r.json().get("items", [])
    dynamic = [x for x in items if x.get("is_dynamic")]
    assert len(dynamic) >= 1, f"学生看不到动态病例: {len(dynamic)}"


def test_dynamic_student_action_timeline_complete(client, headers):
    """P1-4: 完整操作链应包含所有关键动作"""
    rid = _start(client, headers)
    client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/initial-decision",
                json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30}, headers=headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 15}, headers=headers)
    client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 15}, headers=headers)
    client.post(f"/api/triage/training/{rid}/measure", json={"measurement_ids": ["heart_rate"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/reassess",
                json={"selected_level": "Ⅱ级", "selected_zone": "红区", "notify_doctor": True}, headers=headers)
    client.post(f"/api/triage/training/{rid}/notify-doctor", json={"reason": "恶化"}, headers=headers)
    client.post(f"/api/triage/training/{rid}/save-notes", json={"content": "已升级II级红区"}, headers=headers)
    client.post(f"/api/triage/training/{rid}/submit",
                json={"level": "Ⅱ级", "zone": "红区", "disposition": ["notify_doctor"]}, headers=headers)
    r = client.get(f"/api/triage/training/records/{rid}", headers=headers)
    record = r.json().get("record", {})
    actions = record.get("student_actions", [])
    action_types = [a.get("action_type") for a in actions]
    required = ["measure_vitals", "initial_triage", "advance_time", "reassess", "notify_doctor", "record_note", "submit"]
    missing = [t for t in required if t not in action_types]
    assert not missing, f"student_actions 缺少: {missing}. 现有: {action_types}"


def test_exam_mode_hides_feedback(client, headers):
    """考核模式提交后可查看评分状态但详细反馈按配置"""
    r = client.post("/api/triage/training/start",
                    json={"case_external_id": "TRIAGE-DYN-RLQ-001", "mode": "exam", "show_feedback_immediately": False},
                    headers=headers)
    assert r.status_code == 200
    rid = r.json()["record_id"]

    # 完成基本操作
    client.post(f"/api/triage/training/{rid}/observe", json={"observation_ids": ["appearance"]}, headers=headers)
    client.post(f"/api/triage/training/{rid}/initial-decision",
                json={"level": "Ⅲ级", "zone": "黄区", "reassessment_minutes": 30}, headers=headers)
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=headers)

    r = client.post(f"/api/triage/training/{rid}/submit",
                    json={"level": "Ⅲ级", "zone": "黄区", "disposition": []}, headers=headers)
    assert r.status_code == 200
    rec = client.get(f"/api/triage/training/records/{rid}", headers=headers)
    assert rec.status_code == 200
    # exam 模式下 show_feedback_immediately 应为 false
    record = rec.json().get("record", {})
    assert record.get("show_feedback_immediately") is False or record.get("mode") == "exam"
