"""教学管理导出服务。"""

from __future__ import annotations

import csv
import io
from typing import Any

from services.triage_repository import list_records, get_record, get_case
from services.triage_admin_repository import get_task, get_cohort, list_attempts, get_teacher_review


EXPORT_FIELDS = [
    "学员姓名", "班级", "任务名称", "病例名称", "训练模式", "开始时间", "提交时间", "耗时秒",
    "系统评分", "教师复核评分", "最终成绩", "是否合格", "是否触发严重错误", "严重错误原因",
    "初始分诊是否正确", "复评分诊是否正确", "候诊复评是否完成", "通知医生是否完成",
    "主要扣分项", "改进建议",
]


def _find_attempt(record_id: str) -> dict[str, Any] | None:
    return next((a for a in list_attempts() if a.get("record_id") == record_id), None)


def _cohort_name(task: dict[str, Any] | None) -> str:
    if not task:
        return ""
    cohort = get_cohort(task.get("cohort_id") or task.get("class_id"))
    return cohort.get("name", "") if cohort else ""


def _report(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("timeline_report") or {}


def record_to_export_row(record: dict[str, Any]) -> dict[str, Any]:
    task = get_task(record.get("task_id")) if record.get("task_id") else None
    attempt = _find_attempt(record.get("id", ""))
    review = get_teacher_review(attempt.get("attempt_id")) if attempt else None
    case = get_case(record.get("case_external_id", "")) or {}
    report = _report(record)
    serious_reasons = record.get("severe_error_codes") or report.get("serious_error_reasons") or []
    incorrect = report.get("incorrect_points") or []
    suggestions = report.get("improvement_suggestions") or record.get("feedback", {}).get("improvement_suggestions") or []
    decisions = record.get("triage_decisions") or []
    initial_correct = ""
    reassessment_correct = ""
    if decisions:
        init = next((d for d in decisions if d.get("decision_type") == "initial"), None)
        reassess = next((d for d in decisions if d.get("decision_type") == "reassessment"), None)
        initial_correct = "是" if init and init.get("is_correct") else "否" if init else ""
        reassessment_correct = "是" if reassess and reassess.get("is_correct") else "否" if reassess else ""
    reassess_done = bool(record.get("timeline_state", {}).get("reassessments")) or any(a.get("action_type") == "reassess" for a in record.get("student_actions", []))
    notify_done = bool(record.get("notification_events")) or any(a.get("action_type") == "notify_doctor" for a in record.get("student_actions", []))
    system_score = record.get("effective_score", record.get("total_score"))
    teacher_score = review.get("teacher_score") if review else ""
    final_score = review.get("final_score") if review else system_score
    return {
        "学员姓名": record.get("user_display_name", ""),
        "班级": _cohort_name(task),
        "任务名称": task.get("title", "") if task else "",
        "病例名称": case.get("display_name", record.get("case_external_id", "")),
        "训练模式": record.get("mode", ""),
        "开始时间": record.get("started_at", ""),
        "提交时间": record.get("submitted_at", ""),
        "耗时秒": attempt.get("duration_seconds", "") if attempt else "",
        "系统评分": system_score if system_score is not None else "",
        "教师复核评分": teacher_score,
        "最终成绩": final_score if final_score is not None else "",
        "是否合格": "是" if record.get("pass_status") in ("excellent", "good", "pass") else "否",
        "是否触发严重错误": "是" if record.get("severe_error_triggered") else "否",
        "严重错误原因": "；".join(map(str, serious_reasons)),
        "初始分诊是否正确": initial_correct,
        "复评分诊是否正确": reassessment_correct,
        "候诊复评是否完成": "是" if reassess_done else "否",
        "通知医生是否完成": "是" if notify_done else "否",
        "主要扣分项": "；".join(map(str, incorrect[:5])),
        "改进建议": "；".join(map(str, suggestions[:5])),
    }


def build_scores_csv(task_id: str | None = None, class_id: str | None = None) -> str:
    records = []
    for item in list_records(user_id=None):
        record = get_record(item["id"])
        if not record or record.get("total_score") is None:
            continue
        if task_id and record.get("task_id") != task_id:
            continue
        if class_id:
            task = get_task(record.get("task_id")) if record.get("task_id") else None
            if not task or (task.get("cohort_id") != class_id and task.get("class_id") != class_id):
                continue
        records.append(record)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    for record in records:
        writer.writerow(record_to_export_row(record))
    return output.getvalue()
