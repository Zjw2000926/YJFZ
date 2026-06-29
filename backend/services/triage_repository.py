"""预检分诊数据访问层

V1 从 JSON 文件读取数据，提供稳定的 API 给路由层。
后续切数据库时只需修改本模块，不改变 API 和前端。

数据目录结构：
    triage_data/
    ├── manifest.json
    ├── cases/*.json
    ├── rubrics/triage_v1.json
    └── records/*.json  (训练记录存为 JSON 快照)
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from config import TRIAGE_STATIC_DATA_DIR, TRIAGE_RUNTIME_DATA_DIR
from services.case_types import is_dynamic_case

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 静态病例数据（Docker 中可只读挂载）
TRIAGE_DATA_DIR = TRIAGE_STATIC_DATA_DIR
CASES_DIR = os.path.join(TRIAGE_STATIC_DATA_DIR, "cases")
CASES_DYNAMIC_DIR = os.path.join(TRIAGE_STATIC_DATA_DIR, "cases_dynamic")
RUBRICS_DIR = os.path.join(TRIAGE_STATIC_DATA_DIR, "rubrics")
# 运行时训练记录（必须可写）
RECORDS_DIR = os.path.join(TRIAGE_RUNTIME_DATA_DIR, "records")

# 确保 records 目录存在
os.makedirs(RECORDS_DIR, exist_ok=True)

# 内存缓存：避免每次请求都读文件
_case_cache: dict = {}
_cache_loaded = False


def _load_cases():
    """加载全部病例到内存缓存"""
    global _case_cache, _cache_loaded
    if _cache_loaded:
        return
    if not os.path.isdir(CASES_DIR):
        _cache_loaded = True
        return
    for subdir in [CASES_DIR, CASES_DYNAMIC_DIR]:
        if not os.path.isdir(subdir):
            continue
        for fname in sorted(os.listdir(subdir)):
            if fname.endswith(".json"):
                path = os.path.join(subdir, fname)
                with open(path, "r", encoding="utf-8") as f:
                    case = json.load(f)
                try:
                    from services.case_validator import validate_case
                    case["_validation"] = validate_case(case)
                except Exception as exc:
                    case["_validation"] = {
                        "valid": False,
                        "errors": [f"case validation crashed: {exc}"],
                        "warnings": [],
                    }
                eid = case.get("external_id", fname.replace(".json", ""))
                _case_cache[eid] = case
    _cache_loaded = True


def list_cases(include_draft: bool = False) -> list:
    """列出病例摘要。include_draft=True 时返回全部（教师），False 时只返回已审核病例（学生）。"""
    _load_cases()
    result = []
    for eid, case in sorted(_case_cache.items()):
        rs = case.get("review_status") or {}
        if not include_draft and rs.get("approved_for_training") is False:
            continue
        result.append({
            "external_id": eid,
            "display_name": case.get("display_name", case.get("title", "")),
            "difficulty": case.get("difficulty", 1),
            "is_dynamic": is_dynamic_case(case),
            "dynamic_profile": (case.get("_validation") or {}).get("dynamic_profile", {}),
            "training_focus": case.get("training_focus", []),
            "review_status": {"approved_for_training": rs.get("approved_for_training", True)},
            "patient_profile": {
                "age": case.get("patient_profile", {}).get("age"),
                "gender": case.get("patient_profile", {}).get("gender"),
                "arrival_mode": case.get("patient_profile", {}).get("arrival_mode"),
                "appearance": case.get("patient_profile", {}).get("appearance"),
            },
            "initial_exposure": {
                "chief_complaint": case.get("initial_exposure", {}).get("chief_complaint"),
                "opening_line": case.get("initial_exposure", {}).get("opening_line"),
            },
        })
    return result


def get_case(external_id: str) -> Optional[dict]:
    """获取完整病例数据（含标准答案，仅后端评分使用，不可返回前端）"""
    _load_cases()
    return _case_cache.get(external_id)


def get_case_safe(external_id: str) -> Optional[dict]:
    """获取病例安全版本（不含标准答案），用于训练页面"""
    case = get_case(external_id)
    if not case:
        return None
    result = dict(case)
    # P0-B: 移除所有答案字段（训练中不可见）
    for key in ["standard_answer", "severe_errors", "standard_feedback",
                "scoring_rubric", "feedback", "red_flags", "critical_errors",
                "common_errors", "triage_standard", "standard_actions",
                "clinical_information", "review_status", "assessment_checklist",
                # P0-1: 动态病例敏感字段
                "case_type", "is_dynamic", "case_dynamic_type", "dynamic_profile",
                "requires_reassessment", "reassessment_reason",
                "recommended_reassessment_time", "reassessment_triggers",
                "next_state_if_observed", "consequence_if_no_reassessment",
                "reassessment_required_after_node",
                "standard_initial_triage_level", "standard_final_triage_level",
                "standard_initial_area", "standard_final_area",
                "dynamic_scoring_rubric", "dynamic_severe_errors",
                "dynamic_feedback", "required_dynamic_actions",
                "_validation",
                ]:
        result.pop(key, None)

    # P0-1: 脱敏 patient_states — 仅保留当前外观
    ps = case.get("patient_states", [])
    if ps:
        safe_states = []
        for s in ps:
            safe_states.append({
                "state_id": s.get("state_id", ""),
                "time_minute": s.get("time_minute", 0),
                "appearance": s.get("appearance", ""),
            })
        result["patient_states"] = safe_states
    else:
        result.pop("patient_states", None)

    # P0-B: 替换 required_measurements 为 measurement_options（不含值）
    ms = case.get("required_measurements", [])
    result["measurement_options"] = [
        {"id": m.get("id"), "label": m.get("label"), "unit": m.get("unit", ""),
         "category": m.get("category", "vital_sign")}
        for m in ms
    ]
    result.pop("required_measurements", None)

    # 学生前台不暴露动态/时间轴属性；是否复评由学员主动判断。
    dt = case.get("dynamic_timeline")
    if isinstance(dt, dict):
        result["dynamic_timeline"] = {
            "enabled": bool(dt.get("enabled")),
            "has_dynamic_events": bool(dt.get("events")),
        }
    else:
        result.pop("dynamic_timeline", None)

    # P0-B: observation_options
    result["observation_options"] = [
        {"id": "appearance", "label": "一般状态"},
        {"id": "breathing_effort", "label": "呼吸状态"},
        {"id": "skin_perfusion", "label": "皮肤灌注"},
        {"id": "consciousness", "label": "意识状态"},
    ]

    return result


def start_record(user_id: int, external_id: str, user_display_name: str = "",
                 mode: str = "practice", time_limit_minutes: int = None,
                 task_id: str = None, show_feedback_immediately: bool = True) -> dict:
    """创建训练记录"""
    case = get_case(external_id)
    if not case:
        raise ValueError(f"病例不存在: {external_id}")

    record_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "id": record_id,
        "user_id": user_id,
        "user_display_name": user_display_name,
        "case_external_id": external_id,
        "case_id": None,
        "mode": mode,
        "time_limit_minutes": time_limit_minutes,
        "task_id": task_id,
        "show_feedback_immediately": show_feedback_immediately,
        "status": "in_progress",
        "started_at": now,
        "submitted_at": None,
        "total_score": None,
        "pass_status": None,
        "severe_error_triggered": False,
        "severe_error_codes": [],
        "final_level_selected": None,
        "final_zone_selected": None,
        "final_disposition": None,
        "triage_reason": "",
        "notes": [],
        "score_detail": None,
        "feedback": None,
        "messages": [],
        "actions": [],
        "asked_questions": [],
        "measured_vitals": [],
        "created_at": now,
        "updated_at": now,
    }

    # 添加开场白消息
    opening = case.get("initial_exposure", {}).get("opening_line", "你好，我是来看病的。")
    record["messages"].append({
        "role": "patient",
        "content": opening,
        "created_at": now,
    })

    _save_record(record)
    return record


def append_message(record_id: str, role: str, content: str) -> Optional[dict]:
    """追加消息到训练记录"""
    record = _load_record(record_id)
    if not record:
        return None

    record["messages"].append({
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_record(record)
    return record


def record_action(record_id: str, action_type: str, payload: dict) -> Optional[dict]:
    """记录测量/选择等行为"""
    record = _load_record(record_id)
    if not record:
        return None

    action = {
        "action_type": action_type,
        "payload": payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    record["actions"].append(action)

    # 更新对应状态
    if action_type == "measure_vitals":
        record["measured_vitals"] = list(set(
            record.get("measured_vitals", []) + payload.get("measurement_ids", [])
        ))
    elif action_type == "select_level":
        record["final_level_selected"] = payload.get("level")
    elif action_type == "select_zone":
        record["final_zone_selected"] = payload.get("zone")
    elif action_type == "submit_disposition":
        record["final_disposition"] = payload.get("disposition", [])

    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_record(record)
    return record


def submit_record(record_id: str, payload: dict) -> Optional[dict]:
    """提交训练记录（状态变为 submitted）"""
    record = _load_record(record_id)
    if not record:
        return None

    record["status"] = "submitted"
    record["submitted_at"] = datetime.now(timezone.utc).isoformat()
    record["final_level_selected"] = record.get("final_level_selected") or payload.get("level")
    record["final_zone_selected"] = record.get("final_zone_selected") or payload.get("zone")
    record["final_disposition"] = record.get("final_disposition") or payload.get("disposition", [])
    if payload.get("reason"):
        record["triage_reason"] = payload.get("reason")
    if payload.get("note"):
        record.setdefault("notes", []).append({
            "content": payload.get("note"),
            "simulation_minute": (record.get("timeline_state") or {}).get("current_simulated_minute", 0),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_record(record)
    return record


def get_record(record_id: str, user_id: Optional[int] = None) -> Optional[dict]:
    """获取训练记录"""
    record = _load_record(record_id)
    if not record:
        return None
    if user_id is not None and record.get("user_id") != user_id:
        return None
    return record


def list_records(user_id: Optional[int] = None) -> list:
    """列出训练记录"""
    result = []
    if not os.path.isdir(RECORDS_DIR):
        return result
    for fname in os.listdir(RECORDS_DIR):
        if fname.endswith(".json"):
            path = os.path.join(RECORDS_DIR, fname)
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
            if user_id is None or record.get("user_id") == user_id:
                result.append({
                    "id": record["id"],
                    "user_id": record.get("user_id"),
                    "user_display_name": record.get("user_display_name", ""),
                    "case_external_id": record.get("case_external_id"),
                    "mode": record.get("mode"),
                    "task_id": record.get("task_id"),
                    "time_limit_minutes": record.get("time_limit_minutes"),
                    "status": record.get("status"),
                    "total_score": record.get("total_score"),
                    "effective_score": record.get("effective_score"),
                    "pass_status": record.get("pass_status"),
                    "severe_error_triggered": record.get("severe_error_triggered", False),
                    "severe_error_codes": record.get("severe_error_codes", []),
                    "started_at": record.get("started_at"),
                    "submitted_at": record.get("submitted_at"),
                })
    result.sort(key=lambda r: r.get("started_at", ""), reverse=True)
    return result


def delete_records(record_ids: list[str], user_id: Optional[int] = None) -> dict:
    """Delete training record snapshots and report missing or forbidden ids."""
    ids = {str(record_id) for record_id in record_ids if record_id}
    if not ids:
        return {"requested": 0, "deleted": 0, "deleted_ids": [], "missing_ids": []}

    deleted_ids = []
    missing_ids = []
    for record_id in sorted(ids):
        record = _load_record(record_id)
        if not record or (user_id is not None and record.get("user_id") != user_id):
            missing_ids.append(record_id)
            continue
        path = _record_path(record_id)
        try:
            os.remove(path)
            deleted_ids.append(record_id)
        except FileNotFoundError:
            missing_ids.append(record_id)

    return {
        "requested": len(ids),
        "deleted": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "missing_ids": missing_ids,
    }


def save_score(record_id: str, score_data: dict) -> Optional[dict]:
    """保存完整评分结果（含规则依据、标准答案、时间线报告）"""
    record = _load_record(record_id)
    if not record:
        return None

    record["status"] = "scored"
    record["total_score"] = score_data.get("total_score")
    record["pass_status"] = score_data.get("pass_status")
    record["severe_error_triggered"] = score_data.get("severe_error_triggered", False)
    record["severe_error_codes"] = score_data.get("severe_errors", [])
    record["score_detail"] = score_data.get("detail_scores")
    record["score_explanations"] = score_data.get("score_explanations", [])
    record["score_explanation_version"] = score_data.get("score_explanation_version", "")
    record["feedback"] = score_data.get("feedback")
    # P0-2: 完整持久化规则依据、标准答案、时间线报告
    record["rule_result"] = score_data.get("rule_result")
    record["standard_answer"] = score_data.get("standard_answer")
    record["timeline_report"] = score_data.get("timeline_report")
    record["core_scores"] = score_data.get("core_scores")
    record["complex_scores"] = score_data.get("complex_scores")
    record["scoring_version"] = score_data.get("scoring_version", "v4")
    record["rubric_version"] = score_data.get("rubric_version", "")
    record["rule_set_version"] = score_data.get("rule_set_version", "")
    # P0-D: 持久化 criteria 级证据
    record["effective_score"] = score_data.get("effective_score", score_data.get("total_score"))
    record["criterion_scores"] = score_data.get("criterion_scores", [])
    record["critical_failures"] = score_data.get("critical_failures", [])
    record["missed_required_questions"] = score_data.get("feedback", {}).get("missed_required_questions", [])
    record["missed_measurements"] = score_data.get("feedback", {}).get("missed_measurements", [])
    record["missed_red_flags"] = score_data.get("feedback", {}).get("missed_red_flags", [])
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_record(record)
    return record


def _record_path(record_id: str) -> str:
    return os.path.join(RECORDS_DIR, f"{record_id}.json")


def _load_record(record_id: str) -> Optional[dict]:
    path = _record_path(record_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_record(record: dict):
    path = _record_path(record["id"])
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    last_error = None
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.03 * (attempt + 1))
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return
    except PermissionError:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise last_error


def normalize_triage_level(level_str: str) -> str:
    """P1-1: 统一分诊等级格式"""
    if not level_str:
        return "Ⅳ级"
    s = str(level_str).strip().upper()
    mapping = {
        "I": "Ⅰ级", "1": "Ⅰ级", "Ⅰ": "Ⅰ级", "Ⅰ级": "Ⅰ级", "1级": "Ⅰ级",
        "II": "Ⅱ级", "2": "Ⅱ级", "Ⅱ": "Ⅱ级", "Ⅱ级": "Ⅱ级", "2级": "Ⅱ级",
        "III": "Ⅲ级", "3": "Ⅲ级", "Ⅲ": "Ⅲ级", "Ⅲ级": "Ⅲ级", "3级": "Ⅲ级",
        "IV": "Ⅳ级", "4": "Ⅳ级", "Ⅳ": "Ⅳ级", "Ⅳ级": "Ⅳ级", "4级": "Ⅳ级",
    }
    for k, v in mapping.items():
        if k in s:
            return v
    return "Ⅳ级"
