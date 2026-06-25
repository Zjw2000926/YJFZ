import uuid

from auth import hash_password
from models import User


TEACHER_LOGIN = {"username": "teacher_phase3", "password": "teacher123"}
REVIEWER_LOGIN = {"username": "reviewer_phase3", "password": "reviewer123"}
STUDENT_LOGIN = {"username": "student_phase3", "password": "student123"}
OTHER_STUDENT_LOGIN = {"username": "student_phase3_other", "password": "student123"}
STATIC_CASE = "TRIAGE-STATIC-CHEST-II-001"
DYNAMIC_CASE = "TRIAGE-DYN-RLQ-001"
L2 = "Ⅱ级"
RED = "红区"


def _make_user(db_session, username, password, role, name):
    user = db_session.query(User).filter(User.username == username).first()
    if not user:
        user = User(username=username, password_hash=hash_password(password), role=role, display_name=name, student_id=username.upper())
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    return user


def _login(client, payload):
    r = client.post("/api/auth/login", json=payload)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _setup_users(client, db_session):
    teacher = _make_user(db_session, TEACHER_LOGIN["username"], TEACHER_LOGIN["password"], "teacher", "第三阶段教师")
    reviewer = _make_user(db_session, REVIEWER_LOGIN["username"], REVIEWER_LOGIN["password"], "reviewer", "第三阶段审核员")
    student = _make_user(db_session, STUDENT_LOGIN["username"], STUDENT_LOGIN["password"], "student", "第三阶段学员")
    other = _make_user(db_session, OTHER_STUDENT_LOGIN["username"], OTHER_STUDENT_LOGIN["password"], "student", "其他学员")
    return {
        "teacher": teacher,
        "reviewer": reviewer,
        "student": student,
        "other": other,
        "teacher_headers": _login(client, TEACHER_LOGIN),
        "reviewer_headers": _login(client, REVIEWER_LOGIN),
        "student_headers": _login(client, STUDENT_LOGIN),
        "other_headers": _login(client, OTHER_STUDENT_LOGIN),
    }


def _approve(client, headers, case_id=STATIC_CASE):
    r = client.post(f"/api/triage/cases/{case_id}/review", json={"status": "approved", "comment": "phase3"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


def _create_cohort(client, headers, student):
    name = f"Phase3-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/triage/cohorts", json={"name": name, "description": "教学管理MVP"}, headers=headers)
    assert r.status_code == 200, r.text
    cohort = r.json()
    r = client.post(f"/api/triage/cohorts/{cohort['id']}/members", json={"user_id": student.id}, headers=headers)
    assert r.status_code == 200, r.text
    assert any(m["user_id"] == student.id for m in r.json()["members"])
    return r.json()


def _create_task(client, headers, cohort, case_id=STATIC_CASE, mode="practice"):
    title = f"Phase3 Task {uuid.uuid4().hex[:6]}"
    r = client.post("/api/triage/tasks", json={
        "title": title,
        "description": "phase3 assignment",
        "cohort_id": cohort["id"],
        "mode": mode,
        "case_external_ids": [case_id],
        "time_limit_minutes": 12,
        "show_feedback_immediately": mode == "practice",
        "show_standard_answer": False,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _complete_static_attempt(client, student_headers, task):
    r = client.post("/api/triage/training/start", json={
        "case_external_id": STATIC_CASE,
        "task_id": task["id"],
        "mode": "practice",
    }, headers=student_headers)
    assert r.status_code == 200, r.text
    rid = r.json()["record_id"]
    r = client.post(
        f"/api/triage/training/{rid}/measure",
        json={"measurement_ids": [
            "blood_pressure",
            "heart_rate",
            "respiratory_rate",
            "temperature",
            "spo2",
            "pain_score",
            "consciousness",
        ]},
        headers=student_headers,
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/triage/training/{rid}/submit", json={"level": L2, "zone": RED}, headers=student_headers)
    assert r.status_code == 200, r.text
    return rid, r.json()


def test_teacher_can_create_class_and_add_student(client, db_session):
    ctx = _setup_users(client, db_session)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    assert cohort["class_name"].startswith("Phase3-")
    assert ctx["student"].id in cohort["student_ids"]


def test_teacher_can_list_students(client, db_session):
    ctx = _setup_users(client, db_session)
    r = client.get("/api/triage/users?role=student", headers=ctx["teacher_headers"])
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()["items"]}
    assert STUDENT_LOGIN["username"] in usernames
    assert OTHER_STUDENT_LOGIN["username"] in usernames


def test_student_cannot_create_class(client, db_session):
    ctx = _setup_users(client, db_session)
    r = client.post("/api/triage/cohorts", json={"name": "学生越权班级"}, headers=ctx["student_headers"])
    assert r.status_code == 403


def test_teacher_can_publish_training_task_only_with_approved_case(client, db_session):
    ctx = _setup_users(client, db_session)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    client.post(f"/api/triage/cases/{STATIC_CASE}/review", json={"status": "rejected", "comment": "not yet"}, headers=ctx["reviewer_headers"])
    blocked = client.post("/api/triage/tasks", json={
        "title": "Blocked draft/rejected",
        "cohort_id": cohort["id"],
        "mode": "practice",
        "case_external_ids": [STATIC_CASE],
    }, headers=ctx["teacher_headers"])
    assert blocked.status_code == 400
    assert "未审核通过" in str(blocked.json()["detail"])

    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    task = _create_task(client, ctx["teacher_headers"], cohort)
    assert task["assignments"][0]["user_id"] == ctx["student"].id


def test_student_cannot_self_assign_task(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort)
    r = client.post(
        f"/api/triage/tasks/{task['id']}/assign",
        json={"user_id": ctx["other"].id},
        headers=ctx["student_headers"],
    )
    assert r.status_code == 403


def test_student_only_sees_assigned_tasks(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort)
    r = client.get("/api/triage/tasks", headers=ctx["student_headers"])
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()["items"]}
    assert task["id"] in ids
    assert all(any(a["user_id"] == ctx["student"].id for a in t.get("assignments", [])) for t in r.json()["items"])

    r = client.get("/api/triage/tasks", headers=ctx["other_headers"])
    assert task["id"] not in {t["id"] for t in r.json()["items"]}


def test_dynamic_case_review_runs_validator(client, db_session):
    ctx = _setup_users(client, db_session)
    r = client.post(f"/api/triage/cases/{DYNAMIC_CASE}/review", json={"status": "approved", "comment": "validator ok"}, headers=ctx["reviewer_headers"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


def test_reviewer_can_inspect_full_case_review_detail_but_student_cannot(client, db_session):
    ctx = _setup_users(client, db_session)
    detail = client.get(f"/api/triage/cases/{DYNAMIC_CASE}/review-detail", headers=ctx["reviewer_headers"])
    assert detail.status_code == 200, detail.text
    case = detail.json()["case"]
    assert case["external_id"] == DYNAMIC_CASE
    assert case["standard_answer"]["triage_level"]
    assert case["patient_profile"]["age"]
    assert case["validation"]["valid"] is True
    assert len(case["patient_states"]) >= 3

    blocked = client.get(f"/api/triage/cases/{DYNAMIC_CASE}/review-detail", headers=ctx["student_headers"])
    assert blocked.status_code == 403


def test_assignment_attempt_report_review_analytics_and_export(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort)

    rid, submitted = _complete_static_attempt(client, ctx["student_headers"], task)
    assert submitted["record"]["task_id"] == task["id"]

    attempts = client.get("/api/triage/attempts", headers=ctx["student_headers"])
    assert attempts.status_code == 200
    attempt = next(a for a in attempts.json()["items"] if a["record_id"] == rid)
    assert attempt["status"] == "submitted"

    report = client.get(f"/api/triage/training/records/{rid}", headers=ctx["teacher_headers"])
    assert report.status_code == 200
    assert report.json()["record"]["timeline_report"]

    review = client.post(f"/api/triage/training/{rid}/teacher-review", json={"teacher_score": 50, "comment": "需要加强复核"}, headers=ctx["teacher_headers"])
    assert review.status_code == 200, review.text
    system_score = submitted["record"]["total_score"]
    assert review.json()["final_score"] == round(system_score * 0.8 + 50 * 0.2, 1)

    dashboard = client.get(f"/api/triage/stats/class-dashboard/{cohort['id']}", headers=ctx["teacher_headers"])
    assert dashboard.status_code == 200
    assert dashboard.json()["completed_attempts"] >= 1
    assert "average_score" in dashboard.json()
    assert "serious_error_rate" in dashboard.json()

    csv_resp = client.get(f"/api/triage/export/scores.csv?task_id={task['id']}", headers=ctx["teacher_headers"])
    assert csv_resp.status_code == 200
    assert "学员姓名" in csv_resp.text
    assert "最终成绩" in csv_resp.text


def test_teacher_can_release_exam_score_feedback_and_answer(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort, mode="exam")
    rid, _submitted = _complete_static_attempt(client, ctx["student_headers"], task)

    hidden = client.get(f"/api/triage/training/records/{rid}", headers=ctx["student_headers"])
    assert hidden.status_code == 200, hidden.text
    hidden_record = hidden.json()["record"]
    assert hidden_record["mode"] == "exam"
    assert hidden_record["score_released"] is False
    assert hidden_record["show_feedback_immediately"] is False
    assert hidden_record["show_standard_answer"] is False

    released = client.patch(
        f"/api/triage/tasks/{task['id']}/release",
        json={
            "score_released": True,
            "feedback_released": True,
            "standard_answer_released": True,
            "release_note": "release for students",
        },
        headers=ctx["teacher_headers"],
    )
    assert released.status_code == 200, released.text
    assert released.json()["task"]["score_released"] is True
    assert released.json()["task"]["show_feedback_immediately"] is True
    assert released.json()["task"]["show_standard_answer"] is True

    visible = client.get(f"/api/triage/training/records/{rid}", headers=ctx["student_headers"])
    assert visible.status_code == 200, visible.text
    visible_record = visible.json()["record"]
    assert visible_record["score_released"] is True
    assert visible_record["show_feedback_immediately"] is True
    assert visible_record["show_standard_answer"] is True


def test_exam_mode_task_timeline_does_not_show_hints(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], DYNAMIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort, case_id=DYNAMIC_CASE, mode="exam")
    r = client.post("/api/triage/training/start", json={
        "case_external_id": DYNAMIC_CASE,
        "task_id": task["id"],
        "mode": "practice",
    }, headers=ctx["student_headers"])
    assert r.status_code == 200, r.text
    rid = r.json()["record_id"]
    assert r.json()["mode"] == "exam"
    client.post(f"/api/triage/training/{rid}/timeline/advance", json={"minutes": 30}, headers=ctx["student_headers"])
    timeline = client.get(f"/api/triage/training/{rid}/timeline", headers=ctx["student_headers"])
    assert timeline.status_code == 200
    assert all(not e.get("student_prompt") for e in timeline.json()["timeline_events"])


def test_teacher_can_read_student_record(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort)
    rid, _submitted = _complete_static_attempt(client, ctx["student_headers"], task)
    r = client.get(f"/api/triage/training/records/{rid}", headers=ctx["teacher_headers"])
    assert r.status_code == 200
    assert r.json()["record"]["user_id"] == ctx["student"].id


def test_student_cannot_export_score_csv(client, db_session):
    ctx = _setup_users(client, db_session)
    r = client.get("/api/triage/export/scores.csv", headers=ctx["student_headers"])
    assert r.status_code == 403


def test_task_summary_endpoint_reports_completion(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort)
    _complete_static_attempt(client, ctx["student_headers"], task)

    stats = client.get(f"/api/triage/stats/tasks/{task['id']}", headers=ctx["teacher_headers"])
    assert stats.status_code == 200
    assert stats.json()["assigned_count"] == 1
    assert stats.json()["completed_count"] == 1


def test_teacher_can_list_task_attempts(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort)
    rid, _submitted = _complete_static_attempt(client, ctx["student_headers"], task)

    r = client.get(f"/api/triage/tasks/{task['id']}/attempts", headers=ctx["teacher_headers"])
    assert r.status_code == 200
    assert any(a["record_id"] == rid for a in r.json()["items"])


def test_teacher_bulk_delete_tasks_and_missing_task_returns_404(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task_one = _create_task(client, ctx["teacher_headers"], cohort)
    task_two = _create_task(client, ctx["teacher_headers"], cohort)

    deleted = client.post(
        "/api/triage/tasks/bulk-delete",
        json={"ids": [task_one["id"], task_two["id"]]},
        headers=ctx["teacher_headers"],
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == 2

    tasks = client.get("/api/triage/tasks", headers=ctx["teacher_headers"])
    ids = {task["id"] for task in tasks.json()["items"]}
    assert task_one["id"] not in ids
    assert task_two["id"] not in ids

    missing = client.delete("/api/triage/tasks/not-a-real-task", headers=ctx["teacher_headers"])
    assert missing.status_code == 404


def test_teacher_bulk_delete_cohorts(client, db_session):
    ctx = _setup_users(client, db_session)
    cohort_one = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    cohort_two = _create_cohort(client, ctx["teacher_headers"], ctx["student"])

    deleted = client.post(
        "/api/triage/cohorts/bulk-delete",
        json={"ids": [cohort_one["id"], cohort_two["id"]]},
        headers=ctx["teacher_headers"],
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == 2

    cohorts = client.get("/api/triage/cohorts", headers=ctx["teacher_headers"])
    ids = {cohort["id"] for cohort in cohorts.json()["items"]}
    assert cohort_one["id"] not in ids
    assert cohort_two["id"] not in ids


def test_teacher_bulk_delete_training_reports(client, db_session):
    ctx = _setup_users(client, db_session)
    _approve(client, ctx["reviewer_headers"], STATIC_CASE)
    cohort = _create_cohort(client, ctx["teacher_headers"], ctx["student"])
    task = _create_task(client, ctx["teacher_headers"], cohort)
    record_id, _submitted = _complete_static_attempt(client, ctx["student_headers"], task)

    deleted = client.post(
        "/api/triage/training/records/bulk-delete",
        json={"ids": [record_id]},
        headers=ctx["teacher_headers"],
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == 1

    detail = client.get(f"/api/triage/training/records/{record_id}", headers=ctx["teacher_headers"])
    assert detail.status_code == 404
