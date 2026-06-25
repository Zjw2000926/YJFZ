"""教学管理统计服务。

从训练记录、任务和 attempts 聚合班级与任务指标，供教师端看板使用。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from services.triage_repository import list_records, get_record
from services.triage_admin_repository import get_cohort, list_attempts, get_teacher_review


def _score(record: dict[str, Any], attempt: dict[str, Any] | None = None) -> float | None:
    if attempt:
        review = get_teacher_review(attempt.get("attempt_id", ""))
        if review and review.get("final_score") is not None:
            return float(review["final_score"])
    val = record.get("effective_score", record.get("total_score"))
    return float(val) if val is not None else None


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _record_errors(record: dict[str, Any]) -> list[str]:
    codes = record.get("severe_error_codes") or []
    result = []
    for item in codes:
        if isinstance(item, dict):
            result.append(str(item.get("code") or item.get("rule_id") or "unknown"))
        else:
            result.append(str(item))
    for failure in record.get("critical_failures") or []:
        if isinstance(failure, dict):
            result.append(str(failure.get("code") or failure.get("reason") or "critical_failure"))
        else:
            result.append(str(failure))
    return [x for x in result if x]


def compute_class_analytics(class_id: str, assignment_id: str | None = None) -> dict[str, Any]:
    cohort = get_cohort(class_id)
    if not cohort:
        return {"class_id": class_id, "error": "class_not_found"}

    member_ids = {int(m.get("user_id")) for m in cohort.get("members", [])}
    attempts = list_attempts(task_id=assignment_id) if assignment_id else list_attempts()
    attempts = [a for a in attempts if int(a.get("student_id", -1)) in member_ids]
    by_record = {r["id"]: (get_record(r["id"]) or r) for r in list_records(user_id=None)}
    completed = [a for a in attempts if a.get("status") in ("submitted", "scored") and a.get("record_id") in by_record]
    records = [by_record[a["record_id"]] for a in completed]
    scores = [_score(record, attempt) for record, attempt in zip(records, completed)]
    scores = [s for s in scores if s is not None]

    total = len(completed)
    pass_count = sum(1 for r in records if r.get("pass_status") in ("excellent", "good", "pass"))
    excellent_count = sum(1 for s in scores if s >= 90)
    serious_count = sum(1 for r in records if r.get("severe_error_triggered"))

    undertriage = 0
    overtriage = 0
    reassess_needed = 0
    reassess_done = 0
    retriage_needed = 0
    retriage_correct = 0
    notify_needed = 0
    notify_done = 0
    critical_signal_records = 0
    critical_signal_done = 0
    missed_history = Counter()
    missed_vitals = Counter()
    serious_errors = Counter()

    for record in records:
        rule_result = record.get("rule_result") or {}
        if rule_result.get("undertriage") or any("UNDER" in str(c) for c in _record_errors(record)):
            undertriage += 1
        if rule_result.get("overtriage"):
            overtriage += 1
        if record.get("is_dynamic") or record.get("timeline_state"):
            reassess_needed += 1
            if record.get("timeline_state", {}).get("reassessments") or any(a.get("action_type") == "reassess" for a in record.get("student_actions", [])):
                reassess_done += 1
            retriage_needed += 1
            decisions = record.get("triage_decisions") or []
            if any(d.get("decision_type") == "reassessment" and d.get("level") in ("Ⅰ级", "Ⅱ级") for d in decisions):
                retriage_correct += 1
            notify_needed += 1
            if record.get("notification_events") or any(a.get("action_type") == "notify_doctor" for a in record.get("student_actions", [])):
                notify_done += 1
        if record.get("missed_red_flags") is not None:
            critical_signal_records += 1
            if not record.get("missed_red_flags"):
                critical_signal_done += 1
        for item in record.get("missed_required_questions") or []:
            missed_history[str(item)] += 1
        for item in record.get("missed_measurements") or []:
            missed_vitals[str(item)] += 1
        for code in _record_errors(record):
            serious_errors[code] += 1

    return {
        "class_id": class_id,
        "assignment_id": assignment_id,
        "class_name": cohort.get("name", ""),
        "member_count": len(member_ids),
        "completed_attempts": total,
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "pass_rate": _ratio(pass_count, total),
        "excellent_rate": _ratio(excellent_count, total),
        "fail_rate": _ratio(total - pass_count, total),
        "serious_error_rate": _ratio(serious_count, total),
        "undertriage_rate": _ratio(undertriage, total),
        "overtriage_rate": _ratio(overtriage, total),
        "critical_signal_recognition_rate": _ratio(critical_signal_done, critical_signal_records),
        "reassessment_completion_rate": _ratio(reassess_done, reassess_needed),
        "retriage_correct_rate": _ratio(retriage_correct, retriage_needed),
        "notify_doctor_rate": _ratio(notify_done, notify_needed),
        "common_missed_items": [{"item": k, "count": v} for k, v in missed_history.most_common(10)],
        "common_missed_vital_items": [{"item": k, "count": v} for k, v in missed_vitals.most_common(10)],
        "common_serious_errors": [{"code": k, "count": v} for k, v in serious_errors.most_common(10)],
    }


def _compute_task_summary_from(task: dict[str, Any], attempts: list[dict[str, Any]], by_record: dict[str, dict[str, Any]]) -> dict[str, Any]:
    completed = [a for a in attempts if a.get("record_id") in by_record and a.get("status") in ("submitted", "scored")]
    records = [by_record[a["record_id"]] for a in completed]
    scores = [_score(record, attempt) for record, attempt in zip(records, completed)]
    scores = [s for s in scores if s is not None]
    assigned = len(task.get("assignments", []))
    return {
        "assignment_id": task.get("id"),
        "title": task.get("title"),
        "assigned_count": assigned,
        "completed_count": len(completed),
        "unfinished_count": max(assigned - len(completed), 0),
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "highest_score": max(scores) if scores else None,
        "lowest_score": min(scores) if scores else None,
        "serious_error_count": sum(1 for r in records if r.get("severe_error_triggered")),
    }


def compute_task_summary(task: dict[str, Any]) -> dict[str, Any]:
    attempts = list_attempts(task_id=task.get("id"))
    by_record = {r["id"]: r for r in list_records(user_id=None)}
    return _compute_task_summary_from(task, attempts, by_record)


def compute_task_summaries(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """批量计算任务汇总，避免任务列表页对每个任务重复扫描记录文件。"""
    by_record = {r["id"]: r for r in list_records(user_id=None)}
    attempts_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in list_attempts():
        task_id = attempt.get("task_id") or attempt.get("assignment_id")
        if task_id:
            attempts_by_task[task_id].append(attempt)
    return {
        task.get("id"): _compute_task_summary_from(task, attempts_by_task.get(task.get("id"), []), by_record)
        for task in tasks
        if task.get("id")
    }
