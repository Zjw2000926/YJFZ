"""V5/V7 教师端管理数据层 — 班级/任务/病例审核 (JSON存储)

本模块是教学管理 MVP 的持久化边界。当前项目以 JSON 作为运行时数据源，
后续切换数据库时优先替换这里，而不是改训练引擎。
"""

import json, os, uuid
from datetime import datetime, timezone
from html import escape

from config import TRIAGE_RUNTIME_DATA_DIR

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 运行时数据（cohorts/tasks/reviews/versions — 必须可写）
DATA = TRIAGE_RUNTIME_DATA_DIR
COHORTS_FILE = os.path.join(DATA, "cohorts.json")
TASKS_FILE = os.path.join(DATA, "tasks.json")
REVIEWS_FILE = os.path.join(DATA, "case_reviews.json")
ATTEMPTS_FILE = os.path.join(DATA, "assignment_attempts.json")
TEACHER_REVIEWS_FILE = os.path.join(DATA, "teacher_reviews.json")

REVIEW_STATUSES = {"draft", "pending_review", "approved", "rejected", "archived"}


def _now():
    return datetime.now(timezone.utc).isoformat()

def _load(fpath):
    if not os.path.exists(fpath): return []
    with open(fpath, encoding="utf-8") as f: return json.load(f)

def _save(fpath, data):
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    tmp = fpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fpath)  # 原子替换，防止并发损坏


def _student_member(user_id, user_name):
    return {"user_id": int(user_id), "user_name": user_name, "joined_at": _now(), "status": "active"}

# ── Cohorts ──
def list_cohorts(): return _load(COHORTS_FILE)
def get_cohort(cid): return next((c for c in _load(COHORTS_FILE) if c["id"]==cid), None)
def create_cohort(name, description, created_by):
    cohorts = _load(COHORTS_FILE)
    c = {
        "id":str(uuid.uuid4())[:8],
        "class_id": None,
        "name":name,
        "class_name": name,
        "description":description,
        "created_by":created_by,
        "teacher_id": created_by,
        "student_ids": [],
        "start_date": None,
        "end_date": None,
        "status": "active",
        "created_at":_now(),
        "members":[],
    }
    c["class_id"] = c["id"]
    cohorts.append(c); _save(COHORTS_FILE, cohorts); return c
def add_member(cohort_id, user_id, user_name):
    cohorts = _load(COHORTS_FILE)
    for c in cohorts:
        if c["id"]==cohort_id:
            uid = int(user_id)
            if not any(int(m["user_id"])==uid for m in c.get("members", [])):
                c.setdefault("members", []).append(_student_member(uid, user_name))
                c["student_ids"] = sorted(set([int(x) for x in c.get("student_ids", [])] + [uid]))
            _save(COHORTS_FILE, cohorts); return c
    return None


def remove_member(cohort_id, user_id):
    cohorts = _load(COHORTS_FILE)
    for c in cohorts:
        if c["id"] == cohort_id:
            uid = int(user_id)
            c["members"] = [m for m in c.get("members", []) if int(m.get("user_id")) != uid]
            c["student_ids"] = [int(x) for x in c.get("student_ids", []) if int(x) != uid]
            _save(COHORTS_FILE, cohorts)
            return c
    return None

# ── Tasks ──
def _matches_id(item, ids):
    candidates = {
        str(item.get("id", "")),
        str(item.get("class_id", "")),
        str(item.get("assignment_id", "")),
        str(item.get("task_id", "")),
    }
    return bool(candidates & ids)


def _delete_items(fpath, item_ids):
    ids = {str(item_id) for item_id in item_ids if item_id}
    if not ids:
        return {"requested": 0, "deleted": 0, "deleted_ids": [], "missing_ids": []}

    items = _load(fpath)
    kept = []
    deleted_ids = []
    for item in items:
        if _matches_id(item, ids):
            deleted_ids.append(str(item.get("id") or item.get("class_id") or item.get("assignment_id")))
        else:
            kept.append(item)

    if len(kept) != len(items):
        _save(fpath, kept)

    deleted_set = set(deleted_ids)
    return {
        "requested": len(ids),
        "deleted": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "missing_ids": sorted(ids - deleted_set),
    }


def delete_cohorts(cohort_ids):
    """Delete class groups without cascading tasks or records."""
    return _delete_items(COHORTS_FILE, cohort_ids)


def list_tasks(): return _load(TASKS_FILE)
def get_task(tid): return next((t for t in _load(TASKS_FILE) if t["id"]==tid), None)
def list_tasks_for_user(user_id):
    uid = int(user_id)
    return [
        t for t in list_tasks()
        if any(int(a.get("user_id", -1)) == uid for a in t.get("assignments", []))
    ]


def create_task(title, cohort_id, mode, case_ids, created_by, **kw):
    tasks = _load(TASKS_FILE)
    task_id = str(uuid.uuid4())[:8]
    cohort = get_cohort(cohort_id)
    assignments = []
    if cohort:
        for member in cohort.get("members", []):
            assignments.append({
                "assignment_id": f"{task_id}-{member.get('user_id')}",
                "user_id": int(member.get("user_id")),
                "user_name": member.get("user_name", ""),
                "case_ids": case_ids,
                "status": "not_started",
                "best_score": None,
                "latest_record_id": None,
                "attempt_ids": [],
            })
    t = {
         "id": task_id,
         "assignment_id": task_id,
         "title":title,
         "description": kw.get("description", ""),
         "assignment_type": mode,
         "cohort_id":cohort_id,
         "class_id": cohort_id,
         "mode":mode,
         "case_external_ids":case_ids,
         "case_ids": case_ids,
         "teacher_id": created_by,
         "time_limit_minutes":kw.get("time_limit_minutes",8),
         "attempt_limit": kw.get("attempt_limit", 1 if mode == "exam" else 99),
         "allow_hints":kw.get("allow_hints",mode=="practice"),
         "allow_retry":kw.get("allow_retry",mode!="exam"),
         "score_released": kw.get("score_released", mode == "practice"),
         "show_feedback_immediately":kw.get("show_feedback_immediately",mode=="practice"),
         "show_standard_answer": kw.get("show_standard_answer", False if mode == "exam" else kw.get("show_feedback_immediately", True)),
         "results_released_at": kw.get("results_released_at"),
         "results_release_note": kw.get("results_release_note", ""),
         "randomize_case_order": kw.get("randomize_case_order", False),
         "pass_score": kw.get("pass_score", 60),
         "start_time": kw.get("start_time"),
         "end_time": kw.get("end_time"),
         "created_by":created_by,
         "status": kw.get("status", "published"),
         "created_at":_now(),
         "assignments":assignments,
    }
    tasks.append(t); _save(TASKS_FILE, tasks); return t


def update_task_release(task_id, *, score_released=None, feedback_released=None,
                        standard_answer_released=None, release_note=""):
    tasks = _load(TASKS_FILE)
    for task in tasks:
        if task.get("id") != task_id:
            continue
        now = _now()
        if score_released is not None:
            task["score_released"] = bool(score_released)
        if feedback_released is not None:
            task["show_feedback_immediately"] = bool(feedback_released)
        if standard_answer_released is not None:
            task["show_standard_answer"] = bool(standard_answer_released)
        task["results_released_at"] = now
        task["results_release_note"] = release_note or task.get("results_release_note", "")
        task["updated_at"] = now
        _save(TASKS_FILE, tasks)
        return task
    return None


def assign_task(task_id, user_id, user_name, case_ids):
    tasks = _load(TASKS_FILE)
    for t in tasks:
        if t["id"]==task_id:
            uid = int(user_id)
            if not any(int(a.get("user_id", -1)) == uid for a in t.get("assignments", [])):
                t.setdefault("assignments",[]).append({
                    "assignment_id": f"{task_id}-{uid}",
                    "user_id":uid,
                    "user_name":user_name,
                    "case_ids":case_ids or t.get("case_external_ids", []),
                    "status":"not_started",
                    "best_score":None,
                    "latest_record_id":None,
                    "attempt_ids": [],
                })
            _save(TASKS_FILE, tasks); return t
    return None

# ── Case Reviews ──
def list_reviews(): return _load(REVIEWS_FILE)
def review_case(case_id, reviewer_id, status, comment=""):
    if status not in REVIEW_STATUSES:
        raise ValueError(f"不支持的审核状态: {status}")
    reviews = _load(REVIEWS_FILE)
    r = {
        "id":str(uuid.uuid4())[:8],
        "case_id":case_id,
        "reviewer_id":reviewer_id,
        "status":status,
        "comment":comment,
        "review_comments": comment,
        "reviewed_at":_now(),
    }
    reviews.append(r); _save(REVIEWS_FILE, reviews); return r


def get_case_review(case_id):
    reviews = _load(REVIEWS_FILE)
    relevant = [r for r in reviews if r["case_id"]==case_id]
    return relevant[-1] if relevant else {
        "case_id": case_id,
        "status": "draft",
        "comment": "",
        "review_comments": "",
        "reviewer_id": None,
        "reviewed_at": None,
    }


def get_case_review_status(case_id):
    return get_case_review(case_id).get("status", "draft")


def is_case_approved(case_id):
    return get_case_review_status(case_id) == "approved"


def update_assignment_after_score(task_id, user_id, record_id, score):
    """P1-1: 训练提交后回写assignment状态"""
    tasks = _load(TASKS_FILE)
    for t in tasks:
        if t["id"] == task_id:
            for a in t.get("assignments", []):
                if a.get("user_id") == user_id:
                    a["status"] = "scored"
                    a["latest_record_id"] = record_id
                    old = a.get("best_score")
                    a["best_score"] = max(old or 0, score or 0)
                    a["updated_at"] = _now()
                    _save(TASKS_FILE, tasks)
                    return a
    return None


def create_assignment_attempt(task: dict, record: dict) -> dict:
    attempts = _load(ATTEMPTS_FILE)
    attempt = {
        "attempt_id": str(uuid.uuid4())[:12],
        "assignment_id": task.get("id", ""),
        "task_id": task.get("id", ""),
        "case_id": record.get("case_external_id", ""),
        "student_id": record.get("user_id"),
        "record_id": record.get("id"),
        "started_at": record.get("started_at") or _now(),
        "submitted_at": None,
        "duration_seconds": None,
        "mode": record.get("mode", task.get("mode", "practice")),
        "score": None,
        "passed": None,
        "serious_error_triggered": False,
        "report_id": None,
        "status": "in_progress",
    }
    attempts.append(attempt)
    _save(ATTEMPTS_FILE, attempts)
    _link_attempt_to_assignment(task.get("id"), record.get("user_id"), attempt["attempt_id"], "in_progress", record.get("id"))
    return attempt


def complete_assignment_attempt(record: dict) -> dict | None:
    attempts = _load(ATTEMPTS_FILE)
    target = None
    for attempt in attempts:
        if attempt.get("record_id") == record.get("id"):
            target = attempt
            break
    if not target and record.get("task_id"):
        task = get_task(record.get("task_id"))
        if task:
            target = create_assignment_attempt(task, record)
            attempts = _load(ATTEMPTS_FILE)
            target = next((a for a in attempts if a.get("record_id") == record.get("id")), target)
    if not target:
        return None

    submitted_at = record.get("submitted_at") or _now()
    duration = None
    try:
        start = datetime.fromisoformat(str(record.get("started_at")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
        duration = int((end - start).total_seconds())
    except Exception:
        pass
    target.update({
        "submitted_at": submitted_at,
        "duration_seconds": duration,
        "score": record.get("effective_score", record.get("total_score")),
        "passed": record.get("pass_status") in ("excellent", "good", "pass"),
        "serious_error_triggered": bool(record.get("severe_error_triggered")),
        "report_id": record.get("id"),
        "status": "submitted",
    })
    _save(ATTEMPTS_FILE, attempts)
    _link_attempt_to_assignment(record.get("task_id"), record.get("user_id"), target["attempt_id"], "scored", record.get("id"), target.get("score"))
    return target


def _link_attempt_to_assignment(task_id, user_id, attempt_id, status, record_id=None, score=None):
    if not task_id:
        return None
    tasks = _load(TASKS_FILE)
    for task in tasks:
        if task.get("id") != task_id:
            continue
        for assignment in task.get("assignments", []):
            if int(assignment.get("user_id", -1)) != int(user_id):
                continue
            assignment["status"] = status
            if record_id:
                assignment["latest_record_id"] = record_id
            assignment.setdefault("attempt_ids", [])
            if attempt_id and attempt_id not in assignment["attempt_ids"]:
                assignment["attempt_ids"].append(attempt_id)
            if score is not None:
                old = assignment.get("best_score")
                assignment["best_score"] = max(old or 0, score or 0)
            assignment["updated_at"] = _now()
            _save(TASKS_FILE, tasks)
            return assignment
    return None


def list_attempts(task_id=None, student_id=None):
    attempts = _load(ATTEMPTS_FILE)
    if task_id:
        attempts = [a for a in attempts if a.get("task_id") == task_id or a.get("assignment_id") == task_id]
    if student_id is not None:
        attempts = [a for a in attempts if int(a.get("student_id", -1)) == int(student_id)]
    return attempts


def save_teacher_review(attempt_id, teacher_id, system_score, teacher_score, comments="", status="reviewed"):
    teacher_score = max(0, min(100, float(teacher_score)))
    system_score = float(system_score or 0)
    final_score = round(system_score * 0.8 + teacher_score * 0.2, 1)
    reviews = _load(TEACHER_REVIEWS_FILE)
    review = {
        "review_id": str(uuid.uuid4())[:12],
        "attempt_id": attempt_id,
        "teacher_id": teacher_id,
        "system_score": system_score,
        "teacher_score": teacher_score,
        "final_score": final_score,
        "review_comments": comments,
        "review_status": status,
        "reviewed_at": _now(),
    }
    reviews = [r for r in reviews if r.get("attempt_id") != attempt_id]
    reviews.append(review)
    _save(TEACHER_REVIEWS_FILE, reviews)
    return review


def get_teacher_review(attempt_id):
    reviews = [r for r in _load(TEACHER_REVIEWS_FILE) if r.get("attempt_id") == attempt_id]
    return reviews[-1] if reviews else None


def delete_task(task_id):
    """删除任务"""
    return delete_tasks([task_id])


def delete_tasks(task_ids):
    """Delete task definitions without deleting historical attempts or records."""
    return _delete_items(TASKS_FILE, task_ids)


# ── Case Versions ──
VERSIONS_FILE = os.path.join(DATA, "case_versions.json")
def save_case_version(case_id, version, case_data, changed_by, note=""):
    versions = _load(VERSIONS_FILE)
    v = {"id":str(uuid.uuid4())[:8],"case_id":case_id,"version":version,"case_data_snapshot":case_data,"changed_by":changed_by,"change_note":note,"created_at":datetime.now(timezone.utc).isoformat()}
    versions.append(v); _save(VERSIONS_FILE, versions); return v
def list_case_versions(case_id):
    return [v for v in _load(VERSIONS_FILE) if v["case_id"]==case_id]

# ── Export HTML Report ──
def build_html_report(record):
    rd = record
    score = rd.get("total_score", 0)
    ps = rd.get("pass_status", "")
    level = rd.get("final_level_selected", "")
    zone = rd.get("final_zone_selected", "")
    detail = rd.get("score_detail", {})
    timeline = rd.get("timeline_state", {})

    dims_html = "".join(f"<tr><td>{escape(str(k))}</td><td>{escape(str(v.get('score',0)))}/{escape(str(v.get('max',0)))}</td></tr>" for k,v in (detail or {}).items())

    events_html = ""
    for ev in timeline.get("timeline_events", []):
        triggered = "✅" if ev.get("triggered") else "⏳"
        events_html += f"<tr><td>{escape(str(ev.get('scheduled_minute',0)))}min</td><td>{triggered}</td><td>{escape(str(ev.get('patient_expression',''))[:50])}</td></tr>"

    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>预检分诊训练报告</title>
<style>body{{font-family:Arial;max-width:800px;margin:20px auto;padding:20px}}h1{{text-align:center}}h2{{border-bottom:2px solid #2563eb}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #ddd;padding:8px}}th{{background:#f0f4ff}}.score{{font-size:48px;font-weight:bold;text-align:center;color:#2563eb}}.pass{{text-align:center;font-size:20px}}</style></head><body>
<h1>预检分诊训练报告</h1>
<div class='score'>{escape(str(score))}</div><div class='pass'>评级: {escape(str(ps))}</div>
<h2>分诊决策</h2><p>学员选择: {escape(str(level))} / {escape(str(zone))}</p>
<h2>分项评分</h2><table><tr><th>项目</th><th>得分</th></tr>{dims_html}</table>
<h2>时间线</h2><table><tr><th>时间</th><th>触发</th><th>表现</th></tr>{events_html}</table>
<h2>对话记录</h2>{"".join(f"<p><b>{escape(str(m.get('role','')))}</b>: {escape(str(m.get('content','')))[:100]}</p>" for m in rd.get("messages",[]))}
<p style='text-align:center;color:#991b1b;margin-top:32px'>本系统仅用于护理教育训练，不用于真实临床分诊或诊疗决策。</p>
<p style='text-align:center;color:#999'>预检分诊训练系统 — 教学管理模块</p></body></html>"""
