"""P0-01 路由顺序测试
验证 /training/records/all 在 /training/records/{record_id} 之前注册，
教师可访问全局记录，学生被拒绝，个人记录不受影响。
"""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def teacher_token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture
def student_token(client):
    r = client.post("/api/auth/login", json={"username": "student1", "password": "123456"})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_teacher_can_get_all_records(client, teacher_token):
    """P0-01: 教师可以获取全部训练记录"""
    r = client.get("/api/triage/training/records/all",
                   headers={"Authorization": f"Bearer {teacher_token}"})
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data


def test_student_cannot_get_all_records(client, student_token):
    """P0-01: 学生不能获取全部训练记录"""
    r = client.get("/api/triage/training/records/all",
                   headers={"Authorization": f"Bearer {student_token}"})
    assert r.status_code == 403


def test_student_can_get_own_records(client, student_token):
    """P0-01: 学生可以获取自己的训练记录列表"""
    r = client.get("/api/triage/training/records",
                   headers={"Authorization": f"Bearer {student_token}"})
    assert r.status_code == 200
    data = r.json()
    assert "items" in data


def test_record_detail_still_works(client, student_token):
    """P0-01: 路由修复后，/training/records/{record_id} 仍然正常工作（返回404表示路由匹配正确）"""
    r = client.get("/api/triage/training/records/nonexistent-id",
                   headers={"Authorization": f"Bearer {student_token}"})
    # 应返回 404（记录不存在）而非被 all 路由拦截
    assert r.status_code == 404
