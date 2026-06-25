"""P1 观察端点测试
验证 observe_patient 从 required_measurements 读取，
不再返回"未描述"，保存完整 observed_details。
"""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def student_headers(client):
    r = client.post("/api/auth/login", json={"username": "student1", "password": "123456"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _start_and_observe(client, headers, case_id, obs_ids):
    """工具：启动训练并执行观察"""
    r = client.post("/api/triage/training/start",
                    json={"case_external_id": case_id, "mode": "practice"},
                    headers=headers)
    assert r.status_code == 200
    record_id = r.json()["record_id"]

    r = client.post(f"/api/triage/training/{record_id}/observe",
                    json={"observation_ids": obs_ids},
                    headers=headers)
    assert r.status_code == 200
    return record_id, r.json()


def test_observe_returns_all_fields(client, student_headers):
    """每个观察项都含 id/label/value/source"""
    _, data = _start_and_observe(client, student_headers, "TRIAGE-006",
                                 ["appearance", "breathing_effort", "skin_perfusion", "consciousness"])
    for obs in data["observations"]:
        assert "id" in obs, f"missing id in {obs}"
        assert "label" in obs, f"missing label in {obs}"
        assert "value" in obs, f"missing value in {obs}"
        assert "source" in obs, f"missing source in {obs}"


def test_skin_perfusion_not_undescribed(client, student_headers):
    """含 skin_perfusion 的病例不应返回'未描述'"""
    _, data = _start_and_observe(client, student_headers, "TRIAGE-006",
                                 ["skin_perfusion"])
    skin = data["observations"][0]
    assert skin["value"] != "未描述", f"skin_perfusion 不应为未描述: {skin}"


def test_observe_saves_full_details(client, student_headers):
    """观察后重新读取 record 能看到完整 observed_details"""
    record_id, _ = _start_and_observe(client, student_headers, "TRIAGE-006",
                                      ["appearance", "consciousness"])

    r = client.get(f"/api/triage/training/{record_id}/state", headers=student_headers)
    assert r.status_code == 200
    state = r.json()
    assert "observed_items" in state
    assert "observed_details" in state
    assert len(state["observed_items"]) == 2


def test_observe_does_not_return_python_list_string(client, student_headers):
    """观察返回值不应包含 Python 列表字符串"""
    _, data = _start_and_observe(client, student_headers, "TRIAGE-006",
                                 ["appearance", "breathing_effort", "skin_perfusion", "consciousness"])
    for obs in data["observations"]:
        v = str(obs.get("value", ""))
        assert not v.startswith("["), f"发现 Python 列表字符串: {obs['id']} = {v[:50]}"
