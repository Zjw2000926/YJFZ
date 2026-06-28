"""预检分诊训练路由模块 (V1 + V2)

V2 新增：
- variant_id 支持（家属代述/表达不清/默认）
- 意图识别 + 状态机 + LLM受控回答
- GET /state 端点
- V2 评分
"""

import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Optional, List
from auth import get_current_user
from models import User
from database import get_db
from sqlalchemy.orm import Session
from services.triage_repository import (
    list_cases, get_case, get_case_safe,
    start_record, append_message, record_action,
    submit_record, get_record, list_records, save_score,
    normalize_triage_level, delete_records,
)
from services.triage_patient_v1 import match_question, get_vital_signs
from services.triage_scoring_v1 import score_triage_record
from services.triage_scoring_v2 import score_triage_v2
from services.triage_scoring_v3 import score_triage_v3
from services.triage_scoring_v4 import score_triage_v4
from services.triage_scoring_real_rubric import score_triage_real_rubric
from services.triage_intent import match_intent
from services.triage_rules.engine import evaluate as rule_evaluate
from services.triage_stats import get_overview, get_student_stats
from services.triage_admin_repository import (
    list_cohorts, get_cohort, create_cohort, add_member, remove_member,
    list_tasks, list_tasks_for_user, get_task, create_task, assign_task, delete_task, delete_tasks, delete_cohorts,
    update_task_release,
    list_reviews, review_case, get_case_review, get_case_review_status, is_case_approved,
    save_case_version, list_case_versions, build_html_report, build_html_reports,
    build_full_html_report, build_full_html_reports,
    create_assignment_attempt, complete_assignment_attempt, list_attempts,
    save_teacher_review, get_teacher_review as get_stored_teacher_review,
)
from services.analytics_service import compute_class_analytics, compute_task_summary, compute_task_summaries
from services.export_service import build_scores_csv
from services.score_explanation import enrich_score_result
from services.case_types import is_dynamic_case

router = APIRouter(prefix="/api/triage", tags=["预检分诊"])


# ── 请求模型 ──

class TriageStartRequest(BaseModel):
    case_external_id: str
    variant_id: Optional[str] = "default"
    mode: Optional[str] = "practice"
    time_limit_minutes: Optional[int] = None
    task_id: Optional[str] = None

class TriageMessageRequest(BaseModel):
    content: str

class TriageMeasureRequest(BaseModel):
    measurement_ids: Optional[List[str]] = []

class TriageSubmitRequest(BaseModel):
    level: Optional[str] = None
    zone: Optional[str] = None
    disposition: Optional[List[str]] = []
    reason: Optional[str] = ""
    note: Optional[str] = ""


class BulkDeleteRequest(BaseModel):
    ids: List[str] = []


# ── 病例 ──

@router.get("/cases")
def get_cases(current_user: User = Depends(get_current_user)):
    """获取预检分诊病例列表"""
    cases = list_cases(include_draft=current_user.role in ("teacher", "reviewer", "admin"))
    for item in cases:
        review = get_case_review(item.get("external_id"))
        item["case_type"] = "dynamic" if is_dynamic_case(item) else "static"
        item["review_status"] = review.get("status", "draft")
        item["review_comments"] = review.get("review_comments") or review.get("comment", "")
        item["is_available_for_training"] = review.get("status") == "approved"
        item["is_available_for_exam"] = review.get("status") == "approved"
    return {"items": cases, "total": len(cases)}


@router.get("/cases/reviews")
def get_case_reviews_early(current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "reviewer", "admin"):
        raise HTTPException(status_code=403, detail="仅教师/审核员可查看病例审核")
    return {"items": list_reviews()}

@router.post("/cases/{case_id}/review")
def submit_case_review_early(case_id: str, req: dict, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "reviewer", "admin"):
        raise HTTPException(status_code=403, detail="仅教师/审核员可审核病例")
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    status = req.get("status", "approved")
    comment = req.get("comment", "")
    if status == "approved":
        from services.case_validator import validate_case
        result = validate_case(case)
        if not result.get("valid"):
            raise HTTPException(status_code=400, detail={"message": "病例结构校验未通过，不能审核通过", "errors": result.get("errors", [])})
    try:
        return review_case(case_id, current_user.id, status, comment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/cases/{external_id}/review-detail")
def get_case_review_detail(external_id: str, current_user: User = Depends(get_current_user)):
    """审核员查看病例完整审核依据。此接口包含标准答案和评分规则，禁止学生端调用。"""
    if current_user.role not in ("teacher", "reviewer", "admin"):
        raise HTTPException(status_code=403, detail="仅教师/审核员可查看病例审核详情")
    case = get_case(external_id)
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    from services.case_validator import validate_case
    validation = case.get("_validation") or validate_case(case)
    review = get_case_review(external_id)
    return {
        "case": {
            "external_id": case.get("external_id", external_id),
            "title": case.get("title") or case.get("display_name", ""),
            "display_name": case.get("display_name") or case.get("title", ""),
            "case_type": "dynamic" if is_dynamic_case(case) else "static",
            "category": case.get("category", ""),
            "difficulty": case.get("difficulty", 1),
            "target_user": case.get("target_user", ""),
            "training_focus": case.get("training_focus", []),
            "expert_review_required": case.get("expert_review_required", False),
            "patient_profile": case.get("patient_profile", {}),
            "initial_exposure": case.get("initial_exposure", {}),
            "standard_answer": case.get("standard_answer", {}),
            "standard_initial_triage_level": case.get("standard_initial_triage_level"),
            "standard_initial_area": case.get("standard_initial_area"),
            "standard_final_triage_level": case.get("standard_final_triage_level"),
            "standard_final_area": case.get("standard_final_area"),
            "required_questions": case.get("required_questions", []),
            "required_measurements": case.get("required_measurements", []),
            "patient_states": case.get("patient_states", []),
            "dynamic_timeline": case.get("dynamic_timeline", {}),
            "required_dynamic_actions": case.get("required_dynamic_actions", []),
            "scoring_rubric": case.get("scoring_rubric") or case.get("dynamic_scoring_rubric") or {},
            "severe_errors": case.get("severe_errors") or case.get("dynamic_severe_errors") or case.get("critical_errors") or [],
            "dynamic_severe_errors": case.get("dynamic_severe_errors", []),
            "serious_errors": case.get("serious_errors", []),
            "critical_errors": case.get("critical_errors", []),
            "common_errors": case.get("common_errors", []),
            "feedback": case.get("feedback") or case.get("dynamic_feedback") or {},
            "review": review,
            "validation": validation,
        }
    }

@router.get("/cases/{external_id}")
def get_case_detail(external_id: str, current_user: User = Depends(get_current_user)):
    """获取病例详情（安全版，不含标准答案）"""
    case = get_case_safe(external_id)
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    return {"case": case}


# ── 训练 ──

@router.post("/training/start")
def start_training(req: TriageStartRequest, current_user: User = Depends(get_current_user)):
    """开始预检分诊训练"""
    try:
        mode = req.mode or "practice"
        time_limit = req.time_limit_minutes
        show_fb = True if mode == "practice" else False
        task = None
        if req.task_id:
            task = get_task(req.task_id)
            if not task:
                raise HTTPException(status_code=404, detail="任务不存在")
            if not any(int(a.get("user_id", -1)) == int(current_user.id) for a in task.get("assignments", [])):
                raise HTTPException(status_code=403, detail="此任务未分配给当前学员")
            if req.case_external_id not in (task.get("case_external_ids") or []):
                raise HTTPException(status_code=400, detail="病例不属于此任务")
            mode = task.get("mode") or task.get("assignment_type") or mode
            time_limit = task.get("time_limit_minutes") or time_limit
            show_fb = bool(task.get("show_feedback_immediately")) and mode == "practice"
        record = start_record(
            user_id=current_user.id,
            external_id=req.case_external_id,
            user_display_name=current_user.display_name,
            mode=mode,
            time_limit_minutes=time_limit,
            task_id=req.task_id,
            show_feedback_immediately=show_fb,
        )
        if task:
            record["cohort_id"] = task.get("cohort_id")
            record["assignment_type"] = task.get("assignment_type", mode)
            record["show_standard_answer"] = bool(task.get("show_standard_answer")) and mode == "practice"
        # V2: 保存 variant_id
        if req.variant_id:
            record["variant_id"] = req.variant_id
        # V4: 初始化时间线
        case = get_case(req.case_external_id)
        dt = case.get("dynamic_timeline") if case else None
        if case and dt and dt.get("enabled"):
            from services.triage_timeline import initialize_timeline
            record = initialize_timeline(record, case)
            record["timeline_state"]["initial_level_selected"] = None
            # P0-3: 初始化状态机
            from services.triage_state_machine import create_state_machine
            sm = create_state_machine(record)
            record["timeline_state"]["current_stage"] = sm.current_stage
        from services.triage_repository import _save_record
        _save_record(record)
        if task:
            create_assignment_attempt(task, record)
        return {
            "record_id": record["id"],
            "case_external_id": record["case_external_id"],
            "variant_id": req.variant_id,
            "mode": record.get("mode"),
            "task_id": record.get("task_id"),
            "status": record.get("status"),
            "started_at": record.get("started_at"),
            "time_limit_minutes": record.get("time_limit_minutes"),
            "opening_line": record["messages"][0]["content"] if record.get("messages") else "",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/training/records")
def get_records(current_user: User = Depends(get_current_user)):
    """获取训练记录列表"""
    records = list_records(user_id=current_user.id)
    return {"items": records, "total": len(records)}


@router.get("/training/records/all")
def get_all_records(current_user: User = Depends(get_current_user)):
    """教师查看所有训练记录"""
    if current_user.role not in ("teacher", "reviewer", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可查看全部记录")
    from services.triage_repository import list_records
    records = list_records(user_id=None)
    return {"items": records, "total": len(records)}


@router.post("/training/records/bulk-delete")
def bulk_delete_training_records(req: BulkDeleteRequest, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Only teachers can delete training reports")
    result = delete_records(req.ids)
    if result["requested"] > 0 and result["deleted"] == 0:
        raise HTTPException(status_code=404, detail={"message": "No matching training reports were deleted", **result})
    return {"status": "deleted", **result}


@router.delete("/training/records/{record_id}")
def delete_training_record(record_id: str, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Only teachers can delete training reports")
    result = delete_records([record_id])
    if result["deleted"] == 0:
        raise HTTPException(status_code=404, detail="Training report not found")
    return {"status": "deleted", **result}


@router.get("/training/records/{record_id}")
def get_record_detail(record_id: str, current_user: User = Depends(get_current_user)):
    """获取训练记录详情"""
    record = get_record(record_id, user_id=None if current_user.role in ("teacher", "reviewer", "admin") else current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    record = _ensure_record_score_explanations(record)
    task = get_task(record.get("task_id")) if record.get("task_id") else None
    if task:
        record = dict(record)
        record["task_title"] = task.get("title", "")
        record["score_released"] = bool(task.get("score_released", task.get("show_feedback_immediately", record.get("show_feedback_immediately", False))))
        record["show_feedback_immediately"] = bool(task.get("show_feedback_immediately", record.get("show_feedback_immediately", False)))
        record["show_standard_answer"] = bool(task.get("show_standard_answer", record.get("show_standard_answer", False)))
        record["results_released_at"] = task.get("results_released_at")
        record["results_release_note"] = task.get("results_release_note", "")
    return {"record": record}


def _ensure_record_score_explanations(record: dict) -> dict:
    """Backfill criterion-level score explanations for records scored before this feature."""
    case = get_case(record.get("case_external_id", ""))
    if not case:
        return record
    record = dict(record)
    needs_save = False

    try:
        from services.feedback_evidence import FEEDBACK_EVIDENCE_VERSION
        feedback = record.get("feedback") or {}
        if record.get("score_detail") and feedback.get("feedback_version") != FEEDBACK_EVIDENCE_VERSION:
            from services.scoring_engine import score_case
            refreshed = score_case(record, case)
            record["total_score"] = refreshed.get("total_score", record.get("total_score"))
            record["pass_status"] = refreshed.get("pass_status", record.get("pass_status"))
            record["severe_error_triggered"] = refreshed.get("severe_error_triggered", record.get("severe_error_triggered", False))
            record["severe_error_codes"] = refreshed.get("severe_errors", record.get("severe_error_codes", []))
            record["score_detail"] = refreshed.get("detail_scores", record.get("score_detail"))
            record["score_explanations"] = refreshed.get("score_explanations", record.get("score_explanations", []))
            record["score_explanation_version"] = refreshed.get("score_explanation_version", record.get("score_explanation_version", ""))
            record["feedback"] = refreshed.get("feedback", record.get("feedback"))
            record["rule_result"] = refreshed.get("rule_result", record.get("rule_result"))
            record["standard_answer"] = refreshed.get("standard_answer", record.get("standard_answer"))
            record["timeline_report"] = refreshed.get("timeline_report", record.get("timeline_report"))
            record["core_scores"] = refreshed.get("core_scores", record.get("core_scores"))
            record["complex_scores"] = refreshed.get("complex_scores", record.get("complex_scores"))
            record["scoring_version"] = refreshed.get("scoring_version", record.get("scoring_version", ""))
            record["rubric_version"] = refreshed.get("rubric_version", record.get("rubric_version", ""))
            record["rule_set_version"] = refreshed.get("rule_set_version", record.get("rule_set_version", ""))
            record["effective_score"] = refreshed.get("effective_score", refreshed.get("total_score", record.get("effective_score")))
            record["criterion_scores"] = refreshed.get("criterion_scores", record.get("criterion_scores", []))
            record["critical_failures"] = refreshed.get("critical_failures", record.get("critical_failures", []))
            record["missed_required_questions"] = (record.get("feedback") or {}).get("missed_required_questions", [])
            record["missed_measurements"] = (record.get("feedback") or {}).get("missed_measurements", [])
            record["missed_red_flags"] = (record.get("feedback") or {}).get("missed_red_flags", [])
            needs_save = True
    except Exception:
        pass

    detail = record.get("score_detail") or {}
    if not detail:
        return record
    try:
        from services.score_explanation import SCORE_EXPLANATION_VERSION
    except Exception:
        SCORE_EXPLANATION_VERSION = "criteria_v3_history_coverage"
    if record.get("score_explanation_version") == SCORE_EXPLANATION_VERSION and all(isinstance(dim, dict) and dim.get("criteria") for dim in detail.values()):
        if needs_save:
            try:
                from services.triage_repository import _save_record
                _save_record(record)
            except Exception:
                pass
        return record
    score_data = {
        "detail_scores": detail,
        "rule_result": record.get("rule_result") or {},
        "timeline_report": record.get("timeline_report") or {},
        "criterion_scores": record.get("criterion_scores") or [],
    }
    enriched = enrich_score_result(record, case, score_data)
    record = dict(record)
    record["score_detail"] = enriched.get("detail_scores", detail)
    record["score_explanations"] = enriched.get("score_explanations", [])
    record["criterion_scores"] = enriched.get("criterion_scores", record.get("criterion_scores", []))
    record["score_explanation_version"] = enriched.get("score_explanation_version", SCORE_EXPLANATION_VERSION)
    needs_save = True
    if enriched.get("timeline_report"):
        record["timeline_report"] = enriched["timeline_report"]
    if needs_save:
        try:
            from services.triage_repository import _save_record
            _save_record(record)
        except Exception:
            pass
    return record


# ── 对话 ──

@router.post("/training/{record_id}/message")
async def send_message(record_id: str, req: TriageMessageRequest,
                       current_user: User = Depends(get_current_user)):
    """向虚拟患者发送消息（V1：关键词匹配，不调LLM）"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    if record.get("status") != "in_progress":
        raise HTTPException(status_code=400, detail="训练已结束")

    case = get_case(record["case_external_id"])
    if not case:
        raise HTTPException(status_code=500, detail="病例数据丢失")

    # 保存学生消息
    append_message(record_id, "student", req.content)

    # 使用统一拟人化回答服务
    from services.triage_patient_dialogue import generate_triage_patient_reply, require_llm_patient_reply
    dialog_result = await generate_triage_patient_reply(case, record, req.content)

    # 更新记录
    record = _reload(record_id)
    try:
        dialog_result = await require_llm_patient_reply(case, record or {}, req.content, dialog_result)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"虚拟患者 LLM API 调用失败，未生成模板回复：{str(exc)[:200]}",
        )

    patient_reply = dialog_result["content"]
    reply_mode = dialog_result["reply_mode"]
    disclosed = dialog_result["disclosed_slots"]

    if record:
        ie = record.get("intent_events", [])
        if dialog_result["should_append_disclosed"]:
            record["disclosed_slots"] = disclosed
            for ms in dialog_result.get("matched_slots", []):
                ie.append({"intent": dialog_result.get("matched_intents", ["unknown"])[0] if dialog_result.get("matched_intents") else "unknown",
                            "slot": ms, "matched_by": "dialogue_service", "reply_mode": reply_mode})
        elif dialog_result.get("matched_intents"):
            for intent in dialog_result.get("matched_intents", [])[:3]:
                ie.append({"intent": intent, "slot": None, "matched_by": "dialogue_service", "reply_mode": reply_mode})
        record["intent_events"] = ie
        from services.triage_repository import _save_record
        _save_record(record)

    # Log AI events for LLM modes
    if "llm" in reply_mode:
        try:
            from services.triage_v6_services import log_ai_event
            log_ai_event(record_id, "triage_patient", os.getenv("DEEPSEEK_MODEL", ""),
                         "triage_v2@1.0", req.content[:200], patient_reply[:200],
                         {"reply_mode": reply_mode})
        except: pass

    append_message(record_id, "patient", patient_reply)

    return {
        "reply": patient_reply,
        "reply_mode": reply_mode,
        "llm_called": dialog_result.get("llm_called", False),
        "matched": bool(dialog_result.get("matched_slots")),
        "matched_intents": dialog_result.get("matched_intents", []),
        "disclosed_slots": disclosed,
        "asked_count": len(disclosed),
        "total_questions": len(case.get("dialogue_state_machine", {}).get("slots", [])),
    }


def _reload(record_id: str):
    """重新加载记录"""
    return get_record(record_id)


# ── 生命体征测量 ──

@router.post("/training/{record_id}/measure")
def measure_vitals(record_id: str, req: TriageMeasureRequest,
                   current_user: User = Depends(get_current_user)):
    """测量生命体征 — 动态病例返回当前时间点体征"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    if record.get("status") != "in_progress":
        raise HTTPException(status_code=400, detail="训练已结束")

    case = get_case(record["case_external_id"])
    if not case:
        raise HTTPException(status_code=500, detail="病例数据丢失")

    # 获取测量结果
    if not req.measurement_ids:
        mode = record.get("mode", "practice")
        if mode in ("exam", "osce"):
            raise HTTPException(status_code=400, detail="考核模式下请选择需要测量的项目")
        ids = [m["id"] for m in case.get("required_measurements", [])]
    else:
        ids = req.measurement_ids

    # 动态病例: 从当前时间点 patient_state 获取体征
    is_dynamic = is_dynamic_case(case)
    if is_dynamic:
        from services.triage_timeline import record_student_action
        from services.vital_sign_service import measure_multiple_vital_signs
        measurements = measure_multiple_vital_signs(record, case, ids)
        minute = (record.get("timeline_state") or {}).get("current_simulated_minute", 0)
        # P1-3: 先写 student_actions 和更新 measured_vitals，再保存
        record_student_action(record, "measure_vitals", {"ids": ids, "minute": minute})
        record["measured_vitals"] = list(set(record.get("measured_vitals", []) + ids))
        # 记录到 vital_measurement_log
        log = record.get("vital_measurement_log") or []
        log.append({"simulation_minute": minute, "measurement_ids": ids, "result": {m["id"]: m["value"] for m in measurements}})
        record["vital_measurement_log"] = log
        # P0-3: 状态机 — measure_vitals
        try:
            from services.triage_state_machine import create_state_machine
            sm = create_state_machine(record)
            sm.transition("measure_vitals")
        except Exception:
            pass
        from services.triage_repository import _save_record
        _save_record(record)
    else:
        measurements = get_vital_signs(case, ids)

    # 记录 action (静态病例使用旧方式)
    if not is_dynamic:
        record_action(record_id, "measure_vitals", {
            "measurement_ids": [m["id"] for m in measurements],
        })

    return {"measurements": measurements}


# ── 提交分诊 ──

@router.post("/training/{record_id}/submit")
def submit_triage(record_id: str, req: TriageSubmitRequest,
                  current_user: User = Depends(get_current_user)):
    """提交分诊决策并评分"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    if record.get("status") not in ("in_progress",):
        raise HTTPException(status_code=400, detail="训练已提交或已结束")

    case = get_case(record["case_external_id"])
    if not case:
        raise HTTPException(status_code=500, detail="病例数据丢失")

    # 记录选择和提交
    # P1-1: 规范化分诊等级
    normalized_level = normalize_triage_level(req.level) if req.level else None
    if normalized_level:
        record_action(record_id, "select_level", {"level": normalized_level})
    if req.zone:
        record_action(record_id, "select_zone", {"zone": req.zone})
    disposition = req.disposition or []
    reason = (req.reason or "").strip()
    note = (req.note or "").strip()
    if disposition:
        record_action(record_id, "submit_disposition", {"disposition": disposition})
    if reason:
        record_action(record_id, "record_triage_reason", {"reason": reason[:100]})
    if note:
        record_action(record_id, "record_note", {"content": note[:100]})

    # 提交
    submit_record(record_id, {
        "level": normalized_level or req.level,
        "zone": req.zone,
        "disposition": disposition,
        "reason": reason,
        "note": note,
    })

    # 重新加载（已更新状态）
    record = get_record(record_id, user_id=current_user.id)

    # P0-4/P0-2: submit 动作和 COMPLETED 阶段必须先进入记录，再生成报告
    from services.triage_timeline import record_student_action
    record_student_action(record, "submit", {
        "level": normalized_level or req.level,
        "zone": req.zone,
        "disposition": disposition,
        "reason": reason,
        "note": note[:100],
    })
    try:
        from services.triage_state_machine import create_state_machine
        sm = create_state_machine(record)
        sm.transition("submit")
    except Exception:
        pass
    from services.triage_repository import _save_record
    _save_record(record)
    record = get_record(record_id, user_id=current_user.id)

    from services.scoring_engine import score_case
    score_result = score_case(record, case)
    # 防御性校验：评分结果必须有效
    if not isinstance(score_result, dict) or score_result.get("total_score") is None:
        raise HTTPException(status_code=500, detail="评分结果生成失败")

    save_score(record_id, score_result)

    # 确认评分已持久化
    record = get_record(record_id, user_id=current_user.id)
    if record.get("total_score") is None:
        raise HTTPException(status_code=500, detail="评分保存失败")

    # P1-1: 回写任务assignment状态
    from services.triage_admin_repository import update_assignment_after_score
    if record.get("task_id"):
        update_assignment_after_score(
            record["task_id"], current_user.id, record_id,
            score_result.get("effective_score", score_result.get("total_score")),
        )
        complete_assignment_attempt(record)

    # 重新加载含评分
    record = get_record(record_id, user_id=current_user.id)

    return {"record": record, "score": score_result}


# ── V2 新增：训练状态 ──

# ── P1-3: 第一眼观察 ──
class ObserveRequest(BaseModel):
    observation_ids: Optional[List[str]] = []

@router.post("/training/{record_id}/observe")
def observe_patient(record_id: str, req: ObserveRequest,
                    current_user: User = Depends(get_current_user)):
    """第一眼观察动作"""
    record = get_record(record_id, user_id=current_user.id)
    if not record: raise HTTPException(status_code=404)
    if record.get("status") != "in_progress": raise HTTPException(status_code=400)

    case = get_case(record["case_external_id"])
    if not case: raise HTTPException(status_code=500)

    pp = case.get("patient_profile", {})
    current_ps = {}
    current_vitals = {}
    if is_dynamic_case(case):
        try:
            from services.triage_timeline import get_current_patient_state
            current_ps = get_current_patient_state(record, case) or {}
            current_vitals = current_ps.get("state_vitals") or {}
        except Exception:
            current_ps = {}
            current_vitals = {}

    # 辅助：从 required_measurements 按 id 取值
    def _m_by_id(case, mid):
        for item in case.get("required_measurements", []):
            if item.get("id") == mid:
                return item
        return None

    def _display(item):
        if not item:
            return ""
        v = item.get("value")
        u = item.get("unit") or ""
        if v is None or v == "":
            return ""
        return f"{v}{u}" if u and str(v).strip() else str(v)

    def _vital_value(*keys):
        for key in keys:
            if current_vitals.get(key) not in (None, ""):
                return current_vitals.get(key)
        return None

    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _dynamic_appearance():
        return (
            current_ps.get("appearance")
            or current_ps.get("expression")
            or pp.get("appearance")
            or "患者可交流，需继续观察外观、呼吸和皮肤灌注。"
        )

    def _skin_observation():
        text = str(current_ps.get("appearance") or current_ps.get("expression") or "")
        if any(word in text for word in ["苍白", "冷汗", "发绀", "湿冷", "花斑"]):
            return text
        return "未见明显苍白、发绀或冷汗，皮肤灌注暂未见明显异常。"

    def _breathing_observation():
        rr_value = _vital_value("respiratory_rate", "respiratory_rate_bpm")
        if rr_value not in (None, ""):
            return f"呼吸约{rr_value}次/分，需结合血氧和主诉继续判断。"
        return "未见明显呼吸费力，仍需结合SpO₂和主诉评估。"

    def _consciousness_observation():
        value = (
            current_ps.get("mental_status")
            or _vital_value("consciousness", "mental_status")
            or _vital_value("gcs", "gcs_score")
        )
        if value not in (None, ""):
            return str(value)
        return "意识清楚，能交流。"

    rr = _m_by_id(case, "respiratory_rate_bpm")
    skin = _m_by_id(case, "skin_perfusion")
    cons = _m_by_id(case, "consciousness") or _m_by_id(case, "gcs_score")

    OBS_MAP = {
        "appearance": {
            "label": "一般状态",
            "value": _dynamic_appearance(),
            "is_abnormal": False,
            "source": "patient_profile.appearance",
        },
        "breathing_effort": {
            "label": "呼吸状态",
            "value": _breathing_observation() if current_vitals else (_display(rr) or "未见明显呼吸费力，仍需结合SpO₂和主诉评估。"),
            "is_abnormal": bool(rr and rr.get("is_abnormal")) or ((_to_float(_vital_value("respiratory_rate", "respiratory_rate_bpm")) or 0) >= 24),
            "source": "current_patient_state.respiratory_rate",
        },
        "skin_perfusion": {
            "label": "皮肤灌注",
            "value": _display(skin) or _skin_observation(),
            "is_abnormal": bool(skin and skin.get("is_abnormal")) or any(word in _skin_observation() for word in ["苍白", "冷汗", "发绀", "湿冷", "花斑"]),
            "source": "current_patient_state.appearance",
        },
        "consciousness": {
            "label": "意识状态",
            "value": _display(cons) or _consciousness_observation(),
            "is_abnormal": bool(cons and cons.get("is_abnormal")),
            "source": "current_patient_state.mental_status",
        },
    }
    observations = []
    ids_to_fetch = req.observation_ids if req.observation_ids else list(OBS_MAP.keys())
    for obs_id in ids_to_fetch:
        if obs_id in OBS_MAP:
            observations.append({"id": obs_id, **OBS_MAP[obs_id]})

    # 保存完整观察详情
    record_action(record_id, "observe_patient", {
        "observation_ids": [o["id"] for o in observations],
        "observations": observations,
    })
    record = get_record(record_id, user_id=current_user.id)
    if record:
        existing = set(record.get("observed_items", []))
        existing.update(o["id"] for o in observations)
        record["observed_items"] = list(existing)
        record["observed_details"] = observations
        from services.triage_repository import _save_record
        _save_record(record)

    return {"observations": observations}


@router.get("/training/{record_id}/state")
def get_training_state(record_id: str, current_user: User = Depends(get_current_user)):
    """获取训练状态（V2：已披露slot、覆盖情况、测量项、variant等）"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")

    case = get_case(record.get("case_external_id", ""))
    state_machine = case.get("dialogue_state_machine", {}) if case else {}
    all_slots = state_machine.get("slots", [])

    return {
        "record_id": record["id"],
        "disclosed_slots": record.get("disclosed_slots", []),
        "covered_required_slots": [
            s["slot_id"] for s in all_slots
            if s.get("is_required") and s["slot_id"] in record.get("disclosed_slots", [])
        ],
        "total_required_slots": len([s for s in all_slots if s.get("is_required")]),
        "measured_items": record.get("measured_vitals", []),
        "observed_items": record.get("observed_items", []),
        "observed_details": record.get("observed_details", []),
        "current_variant_id": record.get("variant_id", "default"),
        "status": record.get("status"),
    }


# ── V3 新增：规则引擎端点 ──

@router.get("/rules/active")
def get_active_rules(current_user: User = Depends(get_current_user)):
    """获取当前激活的规则集信息"""
    import json, os
    rules_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "triage_data", "rules", "triage_rule_set_v1.json")
    with open(rules_path, encoding="utf-8") as f:
        rules = json.load(f)
    return {
        "rule_set_id": rules.get("id"),
        "version": rules.get("version"),
        "name": rules.get("name"),
        "rule_count": len(rules.get("rules", [])),
        # 教师可看完整规则，学生只看摘要
        "rules": rules.get("rules") if current_user.role == "teacher" else None,
    }


@router.get("/training/{record_id}/rule-result")
def get_rule_result(record_id: str, current_user: User = Depends(get_current_user)):
    """获取训练记录的规则引擎结果"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    if record.get("status") not in ("scored", "submitted"):
        raise HTTPException(status_code=400, detail="评分尚未完成")

    # 如果保存在 score_detail 中
    score_detail = record.get("score_detail", {})
    rule_result = score_detail.get("rule_result")
    if not rule_result:
        # 重新计算
        case = get_case(record.get("case_external_id", ""))
        if case:
            try:
                result = rule_evaluate(case, record)
                rule_result = result.to_dict()
            except Exception:
                rule_result = {"error": "规则计算失败"}

    return {"record_id": record_id, "rule_result": rule_result}


@router.post("/training/{record_id}/recompute-rules")
def recompute_rules(record_id: str, current_user: User = Depends(get_current_user)):
    """重新计算规则（教师权限，用于规则版本升级后复算）"""
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可重新计算规则")

    record = get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")

    case = get_case(record.get("case_external_id", ""))
    if not case:
        raise HTTPException(status_code=500, detail="病例数据丢失")

    result = rule_evaluate(case, record)
    rule_dict = result.to_dict()

    # 保存到记录
    sd = record.get("score_detail", {}) or {}
    sd["rule_result"] = rule_dict
    record["score_detail"] = sd
    from services.triage_repository import _save_record
    _save_record(record)

    return {"record_id": record_id, "rule_result": rule_dict}


# ── V4 新增：动态病例时间轴 + 复评 ──

@router.get("/training/{record_id}/timeline")
def get_timeline(record_id: str, current_user: User = Depends(get_current_user)):
    """获取时间线状态"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    state = record.get("timeline_state", {})
    case = get_case(record.get("case_external_id", ""))
    mode = record.get("mode", "practice")
    # 获取当前 patient_state 的前端展示信息
    from services.triage_timeline import (
        get_current_patient_state,
        normalize_stage_value,
        sanitize_timeline_events_for_mode,
        sanitize_patient_state_for_mode,
    )
    raw_patient_state = get_current_patient_state(record, case) if case else {}
    patient_state = sanitize_patient_state_for_mode(raw_patient_state, mode)
    # P0-2: exam/osce 模式脱敏时间轴事件
    current_minute = state.get("current_simulated_minute", 0)
    safe_events = sanitize_timeline_events_for_mode(state.get("timeline_events", []), mode, current_minute)
    return {
        "current_minute": current_minute,
        "timeline_events": safe_events,
        "reassessments": state.get("reassessments", []),
        "next_reassessment_due": state.get("next_reassessment_due", 30),
        "is_dynamic": record.get("is_dynamic", False),
        "current_stage": normalize_stage_value(state.get("current_stage", "ARRIVAL"), "ARRIVAL"),
        "patient_state": patient_state,
        "triage_decisions": record.get("triage_decisions", []),
        "student_actions": record.get("student_actions", []),
        "mode": mode,
    }


@router.post("/training/{record_id}/timeline/advance")
def advance_timeline(record_id: str, req: dict, current_user: User = Depends(get_current_user)):
    """推进模拟时间"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")

    minutes = req.get("minutes", 5)
    case = get_case(record.get("case_external_id", ""))
    from services.triage_timeline import (
        get_due_events,
        get_current_patient_state,
        record_student_action,
        normalize_stage_value,
        sanitize_timeline_events_for_mode,
        sanitize_patient_state_for_mode,
    )
    events = get_due_events(record, minutes, case)

    mode = record.get("mode", "practice")
    # P1-2: 直接在当前 record 上追加消息，避免 _save_record 覆盖
    for ev in events:
        if ev.get("patient_expression"):
            record.setdefault("messages", []).append({
                "role": "patient",
                "content": ev["patient_expression"],
                "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            })
    # 记录推进动作
    record_student_action(record, "advance_time", {"minutes": minutes, "new_minute": (record.get("timeline_state") or {}).get("current_simulated_minute", 0)})
    # P0-3: 状态机 — 根据是否恶化推进状态
    try:
        from services.triage_state_machine import create_state_machine
        sm = create_state_machine(record)
        state = record.get("timeline_state", {})
        if state.get("deteriorated"):
            sm.mark_deteriorated()
        elif state.get("reassessment_due"):
            sm.mark_reassessment_due()
        else:
            sm.transition("advance_time")
    except Exception:
        pass

    from services.triage_repository import _save_record
    _save_record(record)

    state = record.get("timeline_state", {})
    raw_patient_state = get_current_patient_state(record, case) if case else {}
    patient_state = sanitize_patient_state_for_mode(raw_patient_state, mode)
    current_minute = state.get("current_simulated_minute", 0)
    safe_events = sanitize_timeline_events_for_mode(state.get("timeline_events", []), mode, current_minute)
    due_events = sanitize_timeline_events_for_mode(events, mode, current_minute)
    return {
        "current_minute": current_minute,
        "current_stage": normalize_stage_value(state.get("current_stage", "ARRIVAL"), "ARRIVAL"),
        "patient_state": patient_state,
        "current_patient_state": patient_state,
        "timeline_events": safe_events,
        "visible_events": [e for e in safe_events if e.get("triggered")],
        "due_events": due_events,
        "next_reassessment_due": state.get("next_reassessment_due", 30),
        "reassessment_due": state.get("reassessment_due", False),
        "reassessment_overdue": state.get("reassessment_overdue", False),
        "deteriorated": state.get("deteriorated", False),
        "events": due_events,
    }


@router.post("/training/{record_id}/reassess")
def reassess_patient(record_id: str, req: dict, current_user: User = Depends(get_current_user)):
    """执行复评（含重新分诊决策）"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")

    from services.triage_reassessment import create_reassessment, evaluate_reassessment
    from services.triage_timeline import record_triage_decision, record_student_action
    case = get_case(record.get("case_external_id", ""))
    ra = create_reassessment(record, req, case)
    ev = evaluate_reassessment(record, ra["id"])

    # 记录复评分诊决策（如果学员在复评中选择了新等级）
    upgrade_level = req.get("selected_level")
    upgrade_zone = req.get("selected_zone")
    notify_doctor = req.get("notify_doctor", False)
    if upgrade_level:
        record_triage_decision(record, "reassessment", upgrade_level,
                               area=upgrade_zone or "", notify_doctor=notify_doctor,
                               reason=req.get("reason", ""))
        # P0-4: 如果等级变化，额外记录 upgrade_triage
        init_lv = record.get("timeline_state", {}).get("initial_level_selected")
        if init_lv and upgrade_level != init_lv:
            record_student_action(record, "upgrade_triage", {"from_level": init_lv, "to_level": upgrade_level, "notify_doctor": notify_doctor})
    record_student_action(record, "reassess", {"level": upgrade_level, "notify_doctor": notify_doctor})
    try:
        from services.triage_state_machine import create_state_machine
        sm = create_state_machine(record)
        sm.transition("reassess")
        init_lv = record.get("timeline_state", {}).get("initial_level_selected")
        if upgrade_level and init_lv and upgrade_level != init_lv:
            sm.transition("re_triage")
        if notify_doctor:
            sm.transition("notify_doctor")
    except Exception:
        pass

    from services.triage_repository import _save_record
    _save_record(record)

    return {
        "reassessment_id": ra["id"],
        "rule_result": ra.get("rule_result_after"),
        "upgrade_needed": ra.get("upgrade_needed", False),
        "upgraded_correctly": ra.get("upgraded_correctly"),
        "completeness": ev.get("completeness", 0),
        "feedback_hint": "已记录复评。" if ra.get("upgraded_correctly") else "请检查是否需要升级分诊等级。",
    }


@router.get("/training/{record_id}/current-state")
def get_current_state(record_id: str, current_user: User = Depends(get_current_user)):
    """获取当前患者状态"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    case = get_case(record.get("case_external_id", ""))
    from services.triage_timeline import get_current_patient_state, sanitize_patient_state_for_mode
    raw_ps = get_current_patient_state(record, case)
    return sanitize_patient_state_for_mode(raw_ps, record.get("mode", "practice"))


@router.post("/training/{record_id}/upgrade")
def upgrade_triage(record_id: str, req: dict, current_user: User = Depends(get_current_user)):
    """升级分诊等级"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="训练记录不存在")

    new_level = req.get("level")
    new_zone = req.get("zone")
    if new_level:
        record["final_level_selected"] = new_level
    if new_zone:
        record["final_zone_selected"] = new_zone
    if req.get("disposition"):
        record["final_disposition"] = req.get("disposition")

    # 记录升级为复评决策
    from services.triage_timeline import record_triage_decision, record_student_action
    record_triage_decision(record, "reassessment", new_level, area=new_zone or "",
                           notify_doctor=req.get("notify_doctor", False),
                           reason=req.get("reason", ""))

    state = record.get("timeline_state", {})
    state.setdefault("upgrades", []).append({
        "minute": state.get("current_simulated_minute", 0),
        "to_level": new_level, "to_zone": new_zone,
    })
    record["timeline_state"] = state
    record_student_action(record, "upgrade_triage", {"level": new_level, "zone": new_zone})

    from services.triage_repository import _save_record
    _save_record(record)
    return {"status": "ok", "level": new_level, "zone": new_zone}


@router.post("/training/{record_id}/initial-decision")
def record_initial_decision(record_id: str, req: dict, current_user: User = Depends(get_current_user)):
    """记录初始分诊决策（动态病例第一次分诊）"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404)
    from services.triage_timeline import record_triage_decision, record_student_action
    record = record_triage_decision(record, "initial", req.get("level", ""),
                                     area=req.get("zone", ""),
                                     reassessment_minutes=req.get("reassessment_minutes", 30),
                                     reason=req.get("reason", ""))
    record_student_action(record, "initial_triage", req)
    # P0-2: 状态机 — initial_triage → WAITING
    try:
        from services.triage_state_machine import create_state_machine
        sm = create_state_machine(record)
        sm.transition("initial_triage")
        sm.transition("wait")
    except Exception:
        pass
    from services.triage_repository import _save_record
    _save_record(record)
    return {"status": "ok", "triage_decisions": record.get("triage_decisions", [])}


@router.post("/training/{record_id}/notify-doctor")
def notify_doctor(record_id: str, req: dict, current_user: User = Depends(get_current_user)):
    """通知医生"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404)
    from services.triage_timeline import record_student_action
    record_student_action(record, "notify_doctor", req)
    record.setdefault("notification_events", []).append({
        "simulation_minute": (record.get("timeline_state") or {}).get("current_simulated_minute", 0),
        "reason": req.get("reason", ""),
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    })
    try:
        from services.triage_state_machine import create_state_machine
        sm = create_state_machine(record)
        sm.transition("notify_doctor")
    except Exception:
        pass
    from services.triage_repository import _save_record
    _save_record(record)
    return {"status": "ok"}


@router.post("/training/{record_id}/save-notes")
def save_notes(record_id: str, req: dict, current_user: User = Depends(get_current_user)):
    """保存记录说明"""
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=404)
    from services.triage_timeline import record_student_action
    record_student_action(record, "record_note", {"content": (req.get("content", "") or "")[:50]})
    record.setdefault("notes", []).append({
        "content": req.get("content", ""),
        "simulation_minute": (record.get("timeline_state") or {}).get("current_simulated_minute", 0),
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    })
    # P0-2: 状态机
    try:
        from services.triage_state_machine import create_state_machine
        sm = create_state_machine(record)
        sm.transition("record_notes")
    except Exception:
        pass
    from services.triage_repository import _save_record
    _save_record(record)
    return {"status": "ok"}


# ── V5 新增：统计分析 + 教师复核 + 导出 ──

@router.get("/stats/overview")
def stats_overview(current_user: User = Depends(get_current_user)):
    """总览统计看板（仅教师）"""
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可查看全局统计")
    return get_overview()


@router.get("/stats/students/{user_id}")
def stats_student(user_id: int, current_user: User = Depends(get_current_user)):
    """学员个人能力画像"""
    if current_user.role != "teacher" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="仅教师或本人可查看")
    return get_student_stats(user_id)


@router.get("/stats/error-types")
def stats_error_types(current_user: User = Depends(get_current_user)):
    """错误类型分析（仅教师）"""
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可查看错误类型分析")
    overview = get_overview()
    return {"error_types": overview.get("error_types", [])}


@router.post("/training/{record_id}/teacher-review")
def submit_teacher_review(record_id: str, req: dict, current_user: User = Depends(get_current_user)):
    """教师复核评分（双轨制：系统80% + 教师20%）"""
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可复核")

    record = get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    teacher_score = req.get("teacher_score", req.get("teacher_score_100"))
    if teacher_score is None:
        teacher_score = req.get("teacher_score_20", 0) / 20 * 100
    teacher_score = max(0, min(100, float(teacher_score)))
    comment = req.get("comment", "")
    detail = req.get("review_detail", {})

    system_score = record.get("total_score", 0)
    attempt = next((a for a in list_attempts() if a.get("record_id") == record_id), None)
    if not attempt:
        if record.get("task_id"):
            task = get_task(record["task_id"])
            if task:
                attempt = create_assignment_attempt(task, record)
                complete_assignment_attempt(record)
        attempt = attempt or {"attempt_id": record_id}
    stored_review = save_teacher_review(attempt.get("attempt_id", record_id), current_user.id, system_score, teacher_score, comment)
    final_score = stored_review["final_score"]

    review = {
        "reviewer_id": current_user.id,
        "reviewer_name": current_user.display_name,
        "system_score_100": system_score,
        "teacher_score_20": round(teacher_score / 5, 1),
        "teacher_score_100": teacher_score,
        "final_score": final_score,
        "review_detail": detail,
        "comment": comment,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "attempt_id": attempt.get("attempt_id", record_id),
        "review_id": stored_review.get("review_id"),
    }

    record["teacher_review"] = review
    from services.triage_repository import _save_record
    _save_record(record)

    return {"review": review, "final_score": final_score}


@router.get("/export/record/{record_id}")
def export_record(record_id: str, current_user: User = Depends(get_current_user)):
    """导出单个训练报告"""
    record = get_record(record_id, user_id=None if current_user.role in ("teacher", "reviewer", "admin") else current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


@router.get("/export/all")
def export_all(current_user: User = Depends(get_current_user)):
    """导出全部训练记录 (CSV-ready)"""
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可批量导出")
    from services.triage_repository import list_records
    records = list_records(user_id=None)
    return {"items": records, "total": len(records)}


@router.get("/export/scores.csv")
def export_scores_csv(task_id: Optional[str] = None, class_id: Optional[str] = None,
                      current_user: User = Depends(get_current_user)):
    """导出班级/任务成绩表 CSV。"""
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可导出成绩")
    csv_text = build_scores_csv(task_id=task_id, class_id=class_id)
    return PlainTextResponse(
        content="\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=triage_scores.csv"},
    )


# ── V5 班级/任务/病例审核 ──

from services.triage_admin_repository import (
    list_cohorts, get_cohort, create_cohort, add_member,
    list_tasks, get_task, create_task, assign_task, delete_task, delete_tasks, delete_cohorts,
    list_reviews, review_case, get_case_review_status,
    save_case_version, list_case_versions, build_html_report, build_html_reports,
    build_full_html_report, build_full_html_reports,
)


class CohortCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class TaskCreate(BaseModel):
    title: str
    cohort_id: str
    description: Optional[str] = ""
    mode: str = "practice"
    case_external_ids: List[str] = []
    time_limit_minutes: int = 8
    allow_hints: bool = True
    allow_retry: bool = True
    show_feedback_immediately: bool = True
    show_standard_answer: bool = False
    randomize_case_order: bool = False
    attempt_limit: int = 1
    pass_score: int = 60
    start_time: Optional[str] = None
    end_time: Optional[str] = None

class TaskReleaseUpdate(BaseModel):
    score_released: Optional[bool] = None
    feedback_released: Optional[bool] = None
    standard_answer_released: Optional[bool] = None
    release_note: Optional[str] = ""

class ReviewCreate(BaseModel):
    case_id: str
    status: str = "approved"
    comment: Optional[str] = ""


@router.get("/cohorts")
def get_cohorts(current_user: User = Depends(get_current_user)):
    cohorts = list_cohorts()
    if current_user.role == "student":
        cohorts = [c for c in cohorts if any(int(m.get("user_id", -1)) == int(current_user.id) for m in c.get("members", []))]
    return {"items": cohorts}

@router.post("/cohorts")
def add_cohort(req: CohortCreate, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"): raise HTTPException(status_code=403, detail="当前账号没有教师权限")
    name = (req.name or "").strip()
    if not name: raise HTTPException(status_code=400, detail="班级名称不能为空")
    return create_cohort(name, req.description, current_user.id)

@router.post("/cohorts/bulk-delete")
def bulk_delete_cohorts(req: BulkDeleteRequest, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Only teachers can delete cohorts")
    result = delete_cohorts(req.ids)
    if result["requested"] > 0 and result["deleted"] == 0:
        raise HTTPException(status_code=404, detail={"message": "No matching cohorts were deleted", **result})
    return {"status": "deleted", **result}

@router.delete("/cohorts/{cohort_id}")
def delete_cohort(cohort_id: str, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Only teachers can delete cohorts")
    result = delete_cohorts([cohort_id])
    if result["deleted"] == 0:
        raise HTTPException(status_code=404, detail="Cohort not found")
    return {"status": "deleted", **result}

@router.post("/cohorts/{cohort_id}/members")
def add_cohort_member(cohort_id: str, req: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ("teacher", "admin"): raise HTTPException(status_code=403)
    user = db.query(User).filter(User.id == int(req.get("user_id"))).first()
    if not user or user.role != "student":
        raise HTTPException(status_code=400, detail="只能添加有效学员")
    result = add_member(cohort_id, user.id, req.get("user_name") or user.display_name)
    if not result: raise HTTPException(status_code=404, detail="班级不存在")
    return result

@router.delete("/cohorts/{cohort_id}/members/{user_id}")
def remove_cohort_member(cohort_id: str, user_id: int, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"): raise HTTPException(status_code=403)
    result = remove_member(cohort_id, user_id)
    if not result: raise HTTPException(status_code=404, detail="班级不存在")
    return result

@router.get("/users")
def list_users(role: Optional[str] = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ("teacher", "reviewer", "admin"):
        raise HTTPException(status_code=403, detail="仅教师/管理员可查看用户")
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    users = q.order_by(User.id.asc()).all()
    return {"items": [{
        "user_id": u.id,
        "id": u.id,
        "username": u.username,
        "name": u.display_name,
        "display_name": u.display_name,
        "role": u.role,
        "department": "",
        "class_id": None,
        "student_id": u.student_id,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "status": "active",
    } for u in users]}

@router.get("/tasks")
def get_tasks(current_user: User = Depends(get_current_user)):
    tasks = list_tasks() if current_user.role in ("teacher", "reviewer", "admin") else list_tasks_for_user(current_user.id)
    summaries = compute_task_summaries(tasks)
    for task in tasks:
        summary = summaries.get(task.get("id"))
        task["summary"] = summary if summary is not None else compute_task_summary(task)
    return {"items": tasks}

@router.post("/tasks")
def add_task(req: TaskCreate, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"): raise HTTPException(status_code=403, detail="当前账号没有教师权限")
    title = (req.title or "").strip()
    if not title: raise HTTPException(status_code=400, detail="任务名称不能为空")
    if not req.case_external_ids: raise HTTPException(status_code=400, detail="请选择至少一个病例")
    if not get_cohort(req.cohort_id): raise HTTPException(status_code=400, detail="请选择有效班级")
    missing = [cid for cid in req.case_external_ids if not get_case(cid)]
    if missing: raise HTTPException(status_code=400, detail=f"病例不存在: {', '.join(missing)}")
    unapproved = [cid for cid in req.case_external_ids if not is_case_approved(cid)]
    if unapproved:
        raise HTTPException(status_code=400, detail=f"病例未审核通过，不能发布任务: {', '.join(unapproved)}")
    if req.mode not in ("practice", "exam", "osce"):
        raise HTTPException(status_code=400, detail="任务类型必须是 practice/exam/osce")
    return create_task(title, req.cohort_id, req.mode, req.case_external_ids, current_user.id,
                       description=req.description,
                       time_limit_minutes=req.time_limit_minutes, allow_hints=req.allow_hints and req.mode == "practice",
                       allow_retry=req.allow_retry and req.mode != "exam", show_feedback_immediately=req.show_feedback_immediately and req.mode == "practice",
                       show_standard_answer=req.show_standard_answer and req.mode == "practice",
                       randomize_case_order=req.randomize_case_order, attempt_limit=req.attempt_limit,
                       pass_score=req.pass_score, start_time=req.start_time, end_time=req.end_time)

@router.post("/tasks/bulk-delete")
def bulk_delete_tasks(req: BulkDeleteRequest, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Only teachers can delete tasks")
    result = delete_tasks(req.ids)
    if result["requested"] > 0 and result["deleted"] == 0:
        raise HTTPException(status_code=404, detail={"message": "No matching tasks were deleted", **result})
    return {"status": "deleted", **result}

@router.patch("/tasks/{task_id}/release")
def update_task_release_settings(task_id: str, req: TaskReleaseUpdate, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可发布考核结果")
    if not get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    task = update_task_release(
        task_id,
        score_released=req.score_released,
        feedback_released=req.feedback_released,
        standard_answer_released=req.standard_answer_released,
        release_note=req.release_note or "",
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"status": "updated", "task": task}

@router.post("/tasks/{task_id}/assign")
def assign(task_id: str, req: dict, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可分配任务")
    user_id = req.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="缺少 user_id")
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return assign_task(task_id, user_id, req.get("user_name", ""), req.get("case_ids", task.get("case_external_ids", [])))

@router.delete("/tasks/{task_id}")
def remove_task(task_id: str, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"): raise HTTPException(status_code=403, detail="仅教师可删除任务")
    result = delete_task(task_id)
    if result["deleted"] == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted", **result}

@router.get("/tasks/{task_id}/attempts")
def get_task_attempts(task_id: str, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可查看任务尝试")
    return {"items": list_attempts(task_id=task_id), "summary": compute_task_summary(get_task(task_id) or {})}

@router.get("/attempts")
def get_attempts(current_user: User = Depends(get_current_user)):
    if current_user.role in ("teacher", "reviewer", "admin"):
        return {"items": list_attempts()}
    return {"items": list_attempts(student_id=current_user.id)}


# ── 完整统计 ──

@router.get("/stats/cohorts/{cohort_id}")
def stats_cohort(cohort_id: str, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可查看班级统计")
    cohort = get_cohort(cohort_id)
    if not cohort: raise HTTPException(status_code=404)
    member_ids = [m["user_id"] for m in cohort.get("members",[])]
    records = [r for r in get_records(user_id=None).get("items",[]) if r.get("user_id") in member_ids]
    scored = [r for r in records if r.get("total_score") is not None]
    return {"cohort":cohort,"total_records":len(records),"scored":len(scored),
            "avg_score":round(sum(r.get("total_score",0) for r in scored)/max(len(scored),1),1) if scored else 0,
            "members":len(member_ids)}

@router.get("/stats/tasks/{task_id}")
def stats_task(task_id: str, current_user: User = Depends(get_current_user)):
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可查看任务统计")
    task = get_task(task_id)
    if not task: raise HTTPException(status_code=404)
    return {"task": task, **compute_task_summary(task)}

@router.get("/stats/case-quality")
def stats_case_quality(current_user: User = Depends(get_current_user)):
    from services.triage_repository import list_records
    records = list_records(user_id=None)
    by_case = {}
    for r in records:
        cid = r.get("case_external_id","")
        if cid not in by_case: by_case[cid] = {"count":0,"scores":[]}
        by_case[cid]["count"]+=1
        if r.get("total_score") is not None: by_case[cid]["scores"].append(r["total_score"])
    return {"items":[{"case_id":k,"count":v["count"],"avg_score":round(sum(v["scores"])/max(len(v["scores"]),1),1)} for k,v in by_case.items()]}


@router.get("/stats/class-dashboard/{cohort_id}")
def stats_class_dashboard(cohort_id: str, current_user: User = Depends(get_current_user)):
    """班级维度仪表盘（仅教师）"""
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可查看班级仪表盘")
    analytics = compute_class_analytics(cohort_id)
    if analytics.get("error") == "class_not_found":
        raise HTTPException(status_code=404, detail="班级不存在")
    return analytics


# ── V5 补充：病例版本 + HTML报告 + rubric统计 ──

@router.get("/cases/{case_id}/versions")
def get_case_versions(case_id: str, current_user: User = Depends(get_current_user)):
    return {"items": list_case_versions(case_id)}

@router.post("/cases/{case_id}/versions")
def add_case_version(case_id: str, req: dict, current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    return save_case_version(case_id, req.get("version", 1), req.get("case_data", {}), current_user.id, req.get("note", ""))

@router.get("/export/record/{record_id}/html")
def export_record_html(record_id: str, current_user: User = Depends(get_current_user)):
    """导出训练报告为可打印HTML"""
    record = get_record(record_id, user_id=None if current_user.role in ("teacher", "reviewer", "admin") else current_user.id)
    if not record: raise HTTPException(status_code=404, detail="记录不存在")
    from fastapi.responses import HTMLResponse
    report = _ensure_record_score_explanations(record)
    return HTMLResponse(
        content=build_html_report(report),
        headers={
            "Cache-Control": "no-store",
            "X-Report-Template-Version": "full_detail_v2",
        },
    )

@router.get("/export/record/{record_id}/pdf")
def export_record_pdf(record_id: str, current_user: User = Depends(get_current_user)):
    """打开单份成绩报告的打印页，浏览器可另存为 PDF。"""
    record = get_record(record_id, user_id=None if current_user.role in ("teacher", "reviewer", "admin") else current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    from fastapi.responses import HTMLResponse
    report = _ensure_record_score_explanations(record)
    return HTMLResponse(
        content=build_full_html_report(report, auto_print=True),
        headers={
            "Content-Disposition": f"inline; filename=triage_report_{record_id}.html",
            "Cache-Control": "no-store",
            "X-Report-Template-Version": "full_detail_v2",
        },
    )


def _export_records_pdf_response(record_ids: List[str], current_user: User):
    if current_user.role not in ("teacher", "reviewer", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可批量导出成绩报告")
    ids = [str(item).strip() for item in (record_ids or []) if str(item).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要导出的成绩报告")
    if len(ids) > 200:
        raise HTTPException(status_code=400, detail="一次最多导出 200 份成绩报告")

    reports = []
    missing = []
    for rid in ids:
        record = get_record(rid)
        if not record:
            missing.append(rid)
            continue
        reports.append(_ensure_record_score_explanations(record))
    if not reports:
        raise HTTPException(status_code=404, detail="未找到可导出的成绩报告")

    from fastapi.responses import HTMLResponse
    headers = {
        "Content-Disposition": "inline; filename=triage_reports_batch.html",
        "Cache-Control": "no-store",
        "X-Report-Template-Version": "full_detail_v2",
    }
    if missing:
        headers["X-Missing-Record-Ids"] = ",".join(missing)
    return HTMLResponse(content=build_full_html_reports(reports, auto_print=True), headers=headers)


@router.get("/export/full-report/{record_id}.html")
def export_full_record_report(record_id: str, current_user: User = Depends(get_current_user)):
    """导出单份完整训练报告打印页，包含报告详情页全部核心小节。"""
    record = get_record(record_id, user_id=None if current_user.role in ("teacher", "reviewer", "admin") else current_user.id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    from fastapi.responses import HTMLResponse
    report = _ensure_record_score_explanations(record)
    return HTMLResponse(
        content=build_full_html_report(report, auto_print=True),
        headers={
            "Content-Disposition": f"inline; filename=triage_full_report_{record_id}.html",
            "Cache-Control": "no-store",
            "X-Report-Template-Version": "full_detail_v3",
        },
    )


@router.post("/export/full-reports.html")
def export_full_record_reports(req: BulkDeleteRequest, current_user: User = Depends(get_current_user)):
    """批量导出完整训练报告打印页。"""
    if current_user.role not in ("teacher", "reviewer", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可批量导出成绩报告")
    ids = [str(item).strip() for item in (req.ids or []) if str(item).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要导出的成绩报告")
    if len(ids) > 200:
        raise HTTPException(status_code=400, detail="一次最多导出 200 份成绩报告")
    reports = []
    missing = []
    for rid in ids:
        record = get_record(rid)
        if not record:
            missing.append(rid)
            continue
        reports.append(_ensure_record_score_explanations(record))
    if not reports:
        raise HTTPException(status_code=404, detail="未找到可导出的成绩报告")
    from fastapi.responses import HTMLResponse
    headers = {
        "Content-Disposition": "inline; filename=triage_full_reports_batch.html",
        "Cache-Control": "no-store",
        "X-Report-Template-Version": "full_detail_v3",
    }
    if missing:
        headers["X-Missing-Record-Ids"] = ",".join(missing)
    return HTMLResponse(content=build_full_html_reports(reports, auto_print=True), headers=headers)


@router.get("/export/records/pdf")
def export_records_pdf(ids: str = "", current_user: User = Depends(get_current_user)):
    """兼容 GET 批量导出：ids 使用英文逗号分隔。"""
    return _export_records_pdf_response(ids.split(","), current_user)


@router.post("/export/records/pdf")
def export_records_pdf_post(req: BulkDeleteRequest, current_user: User = Depends(get_current_user)):
    """批量打开成绩报告打印页，浏览器可另存为 PDF。"""
    return _export_records_pdf_response(req.ids, current_user)

@router.get("/stats/rubric-items")
def stats_rubric_items(current_user: User = Depends(get_current_user)):
    """评分维度统计"""
    from services.triage_repository import list_records
    records = list_records(user_id=None)
    scored = [r for r in records if r.get("score_detail")]
    item_stats = {}
    for r in scored:
        for dim_name, dim_data in (r.get("score_detail", {}) or {}).items():
            if isinstance(dim_data, dict):
                if dim_name not in item_stats:
                    item_stats[dim_name] = {"total": 0, "count": 0}
                item_stats[dim_name]["total"] += dim_data.get("score", 0)
                item_stats[dim_name]["count"] += 1
    return {"items": [{"name": k, "avg_score": round(v["total"]/max(v["count"],1), 1), "count": v["count"]} for k, v in item_stats.items()]}


# ── V6 新增：场景+学习路径+科研导出+安全审计+AI日志 ──

from services.triage_v6_services import (
    list_scenarios, get_scenario, create_scenario, add_scenario_patient,
    start_queue_record, save_queue_result,
    generate_learning_path, get_learning_path,
    export_research_data,
    log_safety_audit, list_safety_audits,
    log_ai_event, list_ai_events,
    log_voice_event, list_orgs, create_org, set_case_scope, get_calibration_data,
)
from services.triage_scoring_v6 import score_triage_v6


@router.get("/scenarios")
def get_scenarios(current_user: User = Depends(get_current_user)):
    return {"items": list_scenarios()}

@router.get("/scenarios/{scenario_id}")
def get_scenario_detail(scenario_id: str, current_user: User = Depends(get_current_user)):
    s = get_scenario(scenario_id)
    if not s: raise HTTPException(status_code=404)
    return s

@router.post("/scenarios")
def add_scenario(req: dict, current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    return create_scenario(req.get("external_id", ""), req.get("title", ""), req.get("scenario_type", "queue"),
                           req.get("difficulty", 2), req.get("description", ""))

@router.post("/queue/start")
def start_queue(req: dict, current_user: User = Depends(get_current_user)):
    """启动多人队列（仅学生，且需校验 record 归属）"""
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="仅学生可参与队列训练")
    record_id = req.get("record_id", "")
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=403, detail="无权访问此训练记录")
    return start_queue_record(record_id, req.get("scenario_id", ""))

@router.post("/queue/submit")
def submit_queue(req: dict, current_user: User = Depends(get_current_user)):
    """提交队列结果（需校验 record 归属）"""
    record_id = req.get("record_id", "")
    record = get_record(record_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status_code=403, detail="无权访问此训练记录")
    return save_queue_result(record_id, req.get("priority_order", []),
                             req.get("resource_allocation", {}), req.get("final_score", 0))

@router.get("/learning-path/{user_id}")
def get_user_learning_path(user_id: int, current_user: User = Depends(get_current_user)):
    """读取已有学习路径（只读，不生成新路径）"""
    if current_user.id != user_id and current_user.role != "teacher":
        raise HTTPException(status_code=403)
    path = get_learning_path(user_id)
    if not path:
        raise HTTPException(status_code=404, detail="暂无学习路径，请先生成")
    return path


@router.post("/learning-path/{user_id}/generate")
def generate_user_learning_path(user_id: int, current_user: User = Depends(get_current_user)):
    """生成或刷新学习路径"""
    if current_user.id != user_id and current_user.role != "teacher":
        raise HTTPException(status_code=403)
    from services.triage_stats import get_student_stats
    profile = get_student_stats(user_id)
    path = generate_learning_path(user_id, profile)
    return path

@router.get("/research/export")
def research_export(current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    data = export_research_data(deidentify=True)
    return {"items": data, "total": len(data), "disclaimer": "数据已脱敏，仅用于教学研究"}

@router.get("/research/dataset-schema")
def research_schema(current_user: User = Depends(get_current_user)):
    return {"fields": ["user_anon_id", "case_category", "standard_level", "student_level", "total_score",
                       "pass_status", "severe_error", "disclosed_count", "measured_count",
                       "reassessment_count", "teacher_review_score"],
            "disclaimer": "仅用于教学训练，不用于真实临床分诊。"}

@router.get("/safety/audits")
def get_safety_audits(current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    return {"items": list_safety_audits()}

@router.post("/safety/audits")
def add_safety_audit(req: dict, current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    return log_safety_audit(req.get("audit_type", ""), req.get("target_id", ""),
                            req.get("result", ""), req.get("findings", {}))

@router.get("/ai-events")
def get_ai_events(record_id: Optional[str] = None, current_user: User = Depends(get_current_user)):
    """AI事件日志（仅教师）"""
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可查看AI事件日志")
    return {"items": list_ai_events(record_id)}

@router.post("/ai-events")
def add_ai_event(req: dict, current_user: User = Depends(get_current_user)):
    """记录 AI 事件（需校验 record 归属或教师权限）"""
    record_id = req.get("record_id", "")
    if record_id:
        record = get_record(record_id, user_id=current_user.id)
        if not record and current_user.role != "teacher":
            raise HTTPException(status_code=403, detail="无权为此训练记录写入 AI 事件")
    elif current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可写入全局 AI 事件")
    return log_ai_event(record_id, req.get("purpose", ""), req.get("model", ""),
                        req.get("prompt_version", ""), req.get("input_summary", ""), req.get("output", ""))

# ── V6 语音/组织/校准 ──
@router.post("/voice-events")
def add_voice_event(req: dict, current_user: User = Depends(get_current_user)):
    """记录语音事件（需校验 record 归属或教师权限）"""
    record_id = req.get("record_id", "")
    if record_id:
        record = get_record(record_id, user_id=current_user.id)
        if not record and current_user.role != "teacher":
            raise HTTPException(status_code=403, detail="无权为此训练记录写入语音事件")
    elif current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可写入全局语音事件")
    return log_voice_event(record_id, req.get("transcript", ""),
                           req.get("confidence"), req.get("corrected_transcript"))

@router.get("/organizations")
def get_orgs(current_user: User = Depends(get_current_user)):
    """组织列表（仅教师）"""
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可查看组织列表")
    return {"items": list_orgs()}

@router.post("/organizations")
def add_org(req: dict, current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    return create_org(req.get("name", ""), req.get("type", ""))

@router.post("/case-library-scopes")
def add_scope(req: dict, current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    return set_case_scope(req.get("case_id", ""), req.get("organization_id"), req.get("visibility", "global"))

@router.get("/calibration/score-drift")
def get_score_drift(current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    return get_calibration_data()

@router.get("/calibration/reviewer-disagreement")
def get_reviewer_disagreement(current_user: User = Depends(get_current_user)):
    if current_user.role != "teacher": raise HTTPException(status_code=403)
    data = get_calibration_data()
    disagreements = [r for r in data.get("records", []) if r.get("diff", 0) > 5]
    return {"disagreements": disagreements, "count": len(disagreements), "rate": round(len(disagreements)/max(data.get("count",1),1), 2)}


from datetime import datetime as _dt, timezone as _tz
