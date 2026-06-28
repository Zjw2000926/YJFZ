"""V5/V7 教师端管理数据层 — 班级/任务/病例审核 (JSON存储)

本模块是教学管理 MVP 的持久化边界。当前项目以 JSON 作为运行时数据源，
后续切换数据库时优先替换这里，而不是改训练引擎。
"""

import json, os, time, uuid
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
    tmp = f"{fpath}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    for attempt in range(5):
        try:
            os.replace(tmp, fpath)  # 原子替换，防止并发损坏
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


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

def _as_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _safe(value, default="—"):
    if value is None or value == "":
        return default
    if isinstance(value, (list, tuple)):
        return "、".join(escape(str(item)) for item in value) or default
    if isinstance(value, dict):
        return escape(str(value))
    return escape(str(value))


def _html_list(items, empty="—"):
    values = [item for item in _as_list(items) if item not in (None, "")]
    if not values:
        return f"<span class='muted'>{escape(empty)}</span>"
    return "<ul>" + "".join(f"<li>{_safe(item)}</li>" for item in values) + "</ul>"


def _yes_no(value, yes="是", no="否", unknown="—"):
    if value is True:
        return f"<span class='ok'>{escape(yes)}</span>"
    if value is False:
        return f"<span class='bad'>{escape(no)}</span>"
    return f"<span class='muted'>{escape(unknown)}</span>"


def _score_cell(score, max_score):
    return f"<span class='score-chip'>{_safe(score, '0')} / {_safe(max_score, '?')}</span>"


def _render_basic_info(rd, title):
    timeline_report = rd.get("timeline_report") or {}
    case_info = timeline_report.get("case_info") or {}
    patient = case_info.get("patient_profile") or {}
    effective_score = rd.get("effective_score", rd.get("total_score", ""))
    rows = [
        ("学员", rd.get("user_display_name", ""), "病例", case_info.get("case_name") or rd.get("case_external_id", "")),
        ("病例编号", rd.get("case_external_id", ""), "记录ID", rd.get("id", "")),
        ("训练模式", rd.get("mode", ""), "病例类型", timeline_report.get("case_type") or ("dynamic" if timeline_report.get("is_dynamic_case") else "static")),
        ("开始时间", rd.get("started_at", ""), "提交时间", rd.get("submitted_at", "")),
        ("系统总分", rd.get("total_score", ""), "有效成绩", effective_score),
        ("评级", rd.get("pass_status", ""), "严重错误", "是" if rd.get("severe_error_triggered") else "否"),
        ("患者", f"{patient.get('gender','')} {patient.get('age','')}".strip(), "来院方式", patient.get("arrival_mode", "")),
    ]
    body = "".join(
        f"<tr><th>{escape(left)}</th><td>{_safe(left_v)}</td><th>{escape(right)}</th><td>{_safe(right_v)}</td></tr>"
        for left, left_v, right, right_v in rows
    )
    severe_codes = _html_list(rd.get("severe_error_codes"), "无")
    return f"""<h1>{escape(title)}</h1>
<div class='score'>{_safe(rd.get('total_score', 0))}</div><div class='pass'>评级: {_safe(rd.get('pass_status', ''))}</div>
<h2>基本信息</h2>
<table>{body}</table>
<div class='notice'>本系统仅用于护理教育训练，不用于真实临床分诊或诊疗决策。</div>
<div class='subblock'><b>严重错误代码：</b>{severe_codes}</div>"""


def _render_decision_comparison(rd):
    standard = rd.get("standard_answer") or {}
    timeline_report = rd.get("timeline_report") or {}
    disposition = rd.get("final_disposition") or []
    standard_disposition = standard.get("disposition") or []
    html = f"""
<h2>分诊决策对比</h2>
<table>
  <tr><th></th><th>学员决策</th><th>标准答案</th></tr>
  <tr><th>最终分诊等级</th><td>{_safe(rd.get('final_level_selected'))}</td><td>{_safe(standard.get('triage_level') or timeline_report.get('standard_final_level'))}</td></tr>
  <tr><th>最终就诊区域</th><td>{_safe(rd.get('final_zone_selected'))}</td><td>{_safe(standard.get('triage_zone') or timeline_report.get('standard_final_area'))}</td></tr>
  <tr><th>处置安排</th><td>{_html_list(disposition)}</td><td>{_html_list(standard_disposition)}</td></tr>
  <tr><th>初始分诊</th><td>{_safe(timeline_report.get('student_initial_level'))} / {_safe(timeline_report.get('student_initial_area'))}</td><td>{_safe(timeline_report.get('standard_initial_level'))} / {_safe(timeline_report.get('standard_initial_area'))}</td></tr>
  <tr><th>复评/最终分诊</th><td>{_safe(timeline_report.get('student_final_level') or rd.get('final_level_selected'))} / {_safe(timeline_report.get('student_final_area') or rd.get('final_zone_selected'))}</td><td>{_safe(timeline_report.get('standard_final_level'))} / {_safe(timeline_report.get('standard_final_area'))}</td></tr>
</table>"""
    reason = rd.get("triage_reason") or rd.get("reason") or rd.get("final_reason")
    note = rd.get("note") or rd.get("final_note")
    if reason or note:
        html += f"<div class='subblock'><b>学员分诊理由：</b>{_safe(reason)}<br><b>记录说明：</b>{_safe(note)}</div>"
    return html


def _action_detail(detail):
    if isinstance(detail, dict):
        return "；".join(f"{escape(str(k))}: {_safe(v)}" for k, v in detail.items()) or "—"
    return _safe(detail)


def _render_training_overview(rd):
    timeline_report = rd.get("timeline_report") or {}
    timeline_state = rd.get("timeline_state") or {}
    nodes = timeline_report.get("timeline_nodes") or timeline_report.get("patient_state_timeline") or []
    actions = timeline_report.get("action_timeline") or timeline_report.get("student_actions") or rd.get("student_actions") or []
    vital_logs = timeline_report.get("vital_measurement_log") or timeline_report.get("vital_sign_timeline") or []

    node_rows = "".join(
        f"<tr><td>{_safe(node.get('label') or ('T' + str(node.get('minute', ''))))}</td><td>{_safe(node.get('minute'))}</td><td>{_safe(node.get('event'))}</td><td>{_safe(node.get('stage') or node.get('patient_state_id'))}</td><td>{_safe(node.get('student_action'))}</td></tr>"
        for node in nodes
    )
    action_rows = "".join(
        f"<tr><td>{_safe(action.get('minute') if action.get('minute') is not None else action.get('simulation_minute'))}</td><td>{_safe(action.get('action_type'))}</td><td>{_action_detail(action.get('detail') or action.get('payload'))}</td><td>{_yes_no(action.get('is_correct'), '正确', '不正确')}</td><td>{_safe(action.get('feedback'))}</td></tr>"
        for action in actions
    )
    vital_rows = ""
    for log in vital_logs:
        result = log.get("result") or log.get("vital_signs") or log.get("values") or {}
        vital_rows += f"<tr><td>{_safe(log.get('simulation_minute') if log.get('simulation_minute') is not None else log.get('minute'))}</td><td>{_action_detail(result)}</td></tr>"

    state_events = timeline_state.get("timeline_events") or timeline_state.get("system_events") or []
    state_rows = "".join(
        f"<tr><td>{_safe(ev.get('scheduled_minute') if ev.get('scheduled_minute') is not None else ev.get('simulation_minute'))}</td><td>{_safe(ev.get('event_type'))}</td><td>{_safe(ev.get('patient_expression') or ev.get('event_description') or ev.get('detail'))}</td></tr>"
        for ev in state_events
    )
    status = f"""
<div class='status-grid'>
  <div>按时复评：{_yes_no(timeline_report.get('reassessment_on_time'))}</div>
  <div>复评时间合理：{_yes_no(timeline_report.get('reassessment_reasonable'))}</div>
  <div>识别病情变化：{_yes_no(timeline_report.get('deterioration_recognized'))}</div>
  <div>完成升级分诊：{_yes_no(timeline_report.get('triage_upgraded'))}</div>
  <div>通知医生：{_yes_no(timeline_report.get('doctor_notified'))}</div>
</div>"""

    html = f"<h2>训练流程概览</h2>{status}"
    if node_rows:
        html += f"<h3>患者状态时间线</h3><table><tr><th>节点</th><th>分钟</th><th>事件/表现</th><th>阶段</th><th>学员操作</th></tr>{node_rows}</table>"
    if state_rows:
        html += f"<h3>系统事件时间线</h3><table><tr><th>时间</th><th>事件类型</th><th>内容</th></tr>{state_rows}</table>"
    if action_rows:
        html += f"<h3>学员操作时间线</h3><table><tr><th>时间</th><th>操作类型</th><th>操作内容</th><th>判断</th><th>反馈</th></tr>{action_rows}</table>"
    if vital_rows:
        html += f"<h3>生命体征测量记录</h3><table><tr><th>时间</th><th>测量结果</th></tr>{vital_rows}</table>"
    return html


def _render_score_detail(rd):
    detail = rd.get("score_detail") or {}
    if not detail:
        return "<h2>分项评分</h2><p class='muted'>暂无分项评分。</p>"
    sections = []
    for name, data in detail.items():
        if not isinstance(data, dict):
            sections.append(f"<tr><td>{_safe(name)}</td><td>{_safe(data)}</td><td></td><td></td></tr>")
            continue

        def _criterion_table(criteria, empty_text):
            rows = ""
            for c in criteria:
                status = "完成" if c.get("met") else "未完成"
                rows += f"""
<tr>
  <td>{_safe(c.get('label') or c.get('id'))}</td>
  <td>{_score_cell(c.get('score', 0), c.get('max_score') or c.get('max'))}</td>
  <td>{escape(status)}</td>
  <td>{_safe(c.get('evidence'))}</td>
  <td>{_safe(c.get('deduction_reason') or c.get('missed_reason'))}</td>
  <td>{_safe(c.get('standard_basis'))}</td>
  <td>{_safe(c.get('international_reference'))}</td>
  <td>{_safe(c.get('improvement') or c.get('teaching_point'))}</td>
</tr>"""
            if not rows:
                return f"<p class='muted'>{escape(empty_text)}</p>"
            return f"<table class='small'><tr><th>评分细则</th><th>得分</th><th>状态</th><th>操作证据</th><th>扣分原因</th><th>标准依据</th><th>参考框架</th><th>改进建议</th></tr>{rows}</table>"

        criteria = data.get("criteria") or []
        missed_criteria = [
            c for c in criteria
            if c.get("deduction_reason") or c.get("missed_reason") or c.get("status") == "missed" or c.get("met") is False
        ]
        met_criteria = [c for c in criteria if c not in missed_criteria]
        criteria_table = f"""
  <h4>扣分点</h4>
  {_criterion_table(missed_criteria, '本维度没有扣分点。')}
  <h4>已完成证据</h4>
  {_criterion_table(met_criteria, '本维度暂无已完成证据。')}
"""
        sections.append(f"""
<div class='score-dim'>
  <h3>{_safe(data.get('name') or name)} <span>{_score_cell(data.get('score', 0), data.get('max', 0))}</span></h3>
  <p>{_safe(data.get('summary'))}</p>
  <div><b>扣分原因：</b>{_html_list(data.get('deduction_reasons'), '无')}</div>
  <div><b>已完成证据：</b>{_html_list(data.get('evidence'), '无')}</div>
  <div><b>本项标准依据：</b>{_safe(data.get('standard_basis'))}</div>
  <div><b>国际分诊框架参考：</b>{_safe(data.get('international_reference'))}</div>
  <div><b>改进建议：</b>{_safe(data.get('improvement'))}</div>
  {criteria_table}
</div>""")
    return "<h2>分项评分</h2>" + "".join(sections)


def _render_evidence_detail(rd):
    criterion_scores = rd.get("criterion_scores") or []
    score_explanations = rd.get("score_explanations") or []
    rows = ""
    for item in criterion_scores:
        rows += f"""
<tr>
  <td>{_safe(item.get('criterion') or item.get('dimension'))}</td>
  <td>{_score_cell(item.get('score', 0), item.get('max_score') or item.get('max'))}</td>
  <td>{_yes_no(item.get('met'), '已完成', '未完成')}</td>
  <td>{_html_list(item.get('evidence'), '无')}</td>
  <td>{_safe(item.get('missed_reason'))}</td>
  <td>{_safe(item.get('teaching_point'))}</td>
</tr>"""
    dim_rows = ""
    for dim in score_explanations:
        dim_rows += f"<tr><td>{_safe(dim.get('name'))}</td><td>{_score_cell(dim.get('score', 0), dim.get('max', 0))}</td><td>{_safe(dim.get('summary'))}</td><td>{_html_list(dim.get('deduction_reasons'), '无')}</td></tr>"
    html = "<h2>评分证据明细</h2>"
    if dim_rows:
        html += f"<h3>维度汇总证据</h3><table><tr><th>维度</th><th>得分</th><th>摘要</th><th>主要扣分点</th></tr>{dim_rows}</table>"
    if rows:
        html += f"<h3>评分点证据</h3><table><tr><th>评分点</th><th>得分</th><th>完成情况</th><th>操作证据</th><th>遗漏/扣分原因</th><th>教学提示</th></tr>{rows}</table>"
    if not dim_rows and not rows:
        html += "<p class='muted'>暂无评分证据明细。</p>"
    return html


def _render_feedback(rd):
    feedback = rd.get("feedback") or {}
    evidence = feedback.get("feedback_evidence") or {}
    missed_items = (
        _as_list(feedback.get("missed_required_questions"))
        + _as_list(feedback.get("missed_measurements"))
        + _as_list(feedback.get("missed_red_flags"))
        + _as_list(feedback.get("missed_content"))
    )
    remediation = feedback.get("recommended_remediation") or feedback.get("next_practice_focus")
    return f"""
<h2>专家反馈</h2>
<div class='feedback-grid'>
  <div><h3>正确点</h3>{_html_list(feedback.get('correct_points') or feedback.get('strengths'), '无')}</div>
  <div><h3>正确分诊依据</h3><p>{_safe(feedback.get('reason_for_triage_level'))}</p></div>
  <div><h3>漏掉后的风险</h3>{_html_list(feedback.get('risk_if_missed'), '无')}</div>
  <div><h3>关键高危信号</h3>{_html_list(feedback.get('key_red_flag'), '无')}</div>
  <div><h3>遗漏项</h3>{_html_list(missed_items, '无')}</div>
  <div><h3>补训建议</h3>{_html_list(remediation, '无')}</div>
</div>
<div class='subblock'><b>反馈依据：</b>{_safe(evidence.get('basis'))}<br>
<b>已识别问诊/风险/测量证据：</b>{_html_list(evidence.get('covered_items'), '无')}<br>
<b>已测量项目：</b>{_html_list(evidence.get('measured_items'), '无')}</div>
<div class='critical'><b>安全关键错误：</b>{_html_list(feedback.get('safety_critical_errors') or rd.get('critical_failures'), '无')}</div>"""


def _render_dialogue(rd):
    messages = rd.get("messages") or []
    rows = ""
    for i, msg in enumerate(messages, 1):
        role = "护士/学员" if msg.get("role") in ("student", "user") else "患者"
        rows += f"<tr><td>{i}</td><td>{escape(role)}</td><td>{_safe(msg.get('created_at'))}</td><td class='dialogue'>{_safe(msg.get('content'))}</td></tr>"
    if not rows:
        rows = "<tr><td colspan='4' class='muted'>暂无对话记录。</td></tr>"
    return f"<h2>训练对话记录</h2><table><tr><th>序号</th><th>角色</th><th>时间</th><th>内容</th></tr>{rows}</table>"


def _render_raw_actions(rd):
    actions = rd.get("actions") or []
    if not actions:
        return ""
    rows = "".join(
        f"<tr><td>{_safe(action.get('created_at'))}</td><td>{_safe(action.get('action_type'))}</td><td>{_action_detail(action.get('payload'))}</td></tr>"
        for action in actions
    )
    return f"<h2>原始操作记录</h2><table><tr><th>时间</th><th>操作类型</th><th>内容</th></tr>{rows}</table>"


def _report_section(record, index: int | None = None):
    rd = record
    title = "预检分诊训练报告" if index is None else f"预检分诊训练报告 #{index}"
    return f"""<section class='report-section'>
{_render_basic_info(rd, title)}
{_render_decision_comparison(rd)}
{_render_training_overview(rd)}
{_render_score_detail(rd)}
{_render_evidence_detail(rd)}
{_render_feedback(rd)}
{_render_dialogue(rd)}
{_render_raw_actions(rd)}
<p style='text-align:center;color:#999'>预检分诊训练系统 — 教学管理模块</p></section>"""


def _html_document(body: str, title: str = "预检分诊训练报告", auto_print: bool = False) -> str:
    print_script = """
<script>
window.addEventListener('load', function () {
  setTimeout(function () { window.print(); }, 300);
});
</script>""" if auto_print else ""
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>{escape(title)}</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:900px;margin:20px auto;padding:20px;color:#111827}}
h1{{text-align:center}}h2{{border-bottom:2px solid #2563eb;padding-bottom:4px;margin-top:24px}}
table{{width:100%;border-collapse:collapse;margin:8px 0;table-layout:fixed}}td,th{{border:1px solid #ddd;padding:8px;vertical-align:top;word-break:break-word;white-space:pre-wrap}}th{{background:#f0f4ff}}
ul{{margin:4px 0 4px 18px;padding:0}}li{{margin:2px 0}}h3{{margin:12px 0 6px;font-size:16px;color:#1f2937}}
.score{{font-size:48px;font-weight:bold;text-align:center;color:#2563eb}}.pass{{text-align:center;font-size:20px}}
.print-tip{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:10px;margin-bottom:16px;color:#1e40af;font-size:13px}}
.notice{{background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:8px;margin:10px 0;color:#991b1b;font-size:13px}}
.subblock{{background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:8px;margin:10px 0;font-size:13px}}
.critical{{background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:8px;margin:10px 0;font-size:13px;color:#9a3412}}
.status-grid,.feedback-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:8px 0}}
.status-grid>div,.feedback-grid>div{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:8px}}
.score-dim{{border:1px solid #e5e7eb;border-radius:8px;padding:10px;margin:12px 0;break-inside:avoid}}
.score-dim h3{{display:flex;justify-content:space-between;gap:12px}}
.score-chip{{font-weight:700;color:#2563eb;white-space:nowrap}}
.small{{font-size:12px}}.muted{{color:#6b7280}}.ok{{color:#16a34a;font-weight:700}}.bad{{color:#dc2626;font-weight:700}}
.dialogue{{line-height:1.55}}
.report-section{{page-break-after:always;margin-bottom:36px}}.report-section:last-child{{page-break-after:auto}}
@media print{{body{{margin:0;max-width:none;padding:12mm;font-size:12px}}.print-tip{{display:none}}.report-section{{break-after:page}}.report-section:last-child{{break-after:auto}}h2{{break-after:avoid}}tr,.score-dim,.subblock,.critical{{break-inside:avoid}}}}
</style>{print_script}</head><body>
<div class='print-tip'>导出 PDF：请在打印窗口选择“另存为 PDF”或“Microsoft Print to PDF”。</div>
{body}
</body></html>"""


# ── Export HTML Report ──
def build_html_report(record, auto_print: bool = False):
    return _html_document(_report_section(record), auto_print=auto_print)


def build_html_reports(records, auto_print: bool = False):
    sections = "".join(_report_section(record, index + 1) for index, record in enumerate(records or []))
    return _html_document(sections or "<p>没有可导出的报告。</p>", title="预检分诊批量训练报告", auto_print=auto_print)


def build_full_html_report(record, auto_print: bool = False):
    """完整训练报告导出模板。使用独立函数名，避免旧简版导出缓存误用。"""
    return build_html_report(record, auto_print=auto_print)


def build_full_html_reports(records, auto_print: bool = False):
    """批量完整训练报告导出模板。"""
    return build_html_reports(records, auto_print=auto_print)
