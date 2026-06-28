"""V4 动态病例时间轴管理 — MVP 扩展版

支持: 绝对分钟推进、patient_states、事件类型、训练/考核模式提示、复评逾期检测。
"""

import json, os, copy
from datetime import datetime, timezone
from typing import Optional

VALID_STAGE_VALUES = {
    "NOT_STARTED", "ARRIVAL", "FIRST_LOOK", "HISTORY_TAKING", "INITIAL_VITALS",
    "INITIAL_TRIAGE", "WAITING", "REASSESSMENT_DUE", "DETERIORATED",
    "REASSESSMENT", "RE_TRIAGE", "FINAL_DISPOSITION", "COMPLETED",
}


def normalize_stage_value(value, fallback: str = "ARRIVAL") -> str:
    """把病例数据中的阶段字段统一为状态机可识别的字符串。

    部分批量迁移病例把 initial_stage 写成了包含标准答案的对象，
    这里不能直接作为 current_stage 返回给前端或状态机。
    """
    if isinstance(value, str) and value in VALID_STAGE_VALUES:
        return value
    if isinstance(value, dict):
        for key in ("stage", "state", "current_stage"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate in VALID_STAGE_VALUES:
                return candidate
        return fallback
    return fallback


def initialize_timeline(record: dict, case_data: dict) -> dict:
    """初始化时间轴状态"""
    dt = case_data.get("dynamic_timeline", {})
    if not dt.get("enabled"):
        return record

    events = dt.get("events", [])
    timeline_events = []
    for ev in events:
        timeline_events.append({
            "event_id": ev.get("event_id", ""),
            "scheduled_minute": ev.get("scheduled_minute", 0),
            "event_type": ev.get("event_type", "info"),
            "triggered": False,
            "patient_state_id": ev.get("patient_state_id", ""),
            "event_description": ev.get("event_description", ""),
            "visible_to_student": ev.get("visible_to_student", True),
            "student_prompt": ev.get("student_prompt", ""),
            "patient_expression": ev.get("patient_expression", ""),
            "vital_changes": ev.get("vital_changes", {}),
            "requires_reassessment": ev.get("requires_reassessment", False),
            "expected_student_actions": ev.get("expected_student_actions", []),
            "consequence_if_missed": ev.get("consequence_if_missed", ""),
            "standard_level_after_event": ev.get("standard_level_after_event", ""),
            "severe_error_if_ignored": ev.get("severe_error_if_ignored", False),
            "severe_error_code": ev.get("severe_error_code", ""),
        })

    raw_init_stage = dt.get("initial_stage", "ARRIVAL")
    init_stage = normalize_stage_value(raw_init_stage, "ARRIVAL")
    state = {
        "current_stage": init_stage,
        "current_simulated_minute": 0,
        "current_patient_state_id": "T0_initial",
        "current_patient_state": {
            "expression": case_data.get("initial_exposure", {}).get("opening_line", ""),
            "appearance": case_data.get("patient_profile", {}).get("appearance", ""),
        },
        "current_vitals": {},
        "last_reassessment_minute": 0,
        "next_reassessment_due": 30,
        "reassessment_required_items": dt.get("reassessment_required_items", []),
        "reassessments": [],
        "timeline_events": timeline_events,
        "initial_level_selected": None,
        "upgrades": [],
        "system_events": [],
        "mode": record.get("mode", "practice"),
        "reassessment_overdue": False,
    }
    if isinstance(raw_init_stage, dict):
        state["initial_stage_metadata"] = copy.deepcopy(raw_init_stage)

    record["timeline_state"] = state
    record["is_dynamic"] = True
    return record


def _get_patient_state(case_data: dict, state_id: Optional[str] = None, minute: int = 0) -> Optional[dict]:
    """从 patient_states 中按 state_id 或 time_minute 查找"""
    states = case_data.get("patient_states", [])
    if not states:
        return None
    if state_id:
        for s in states:
            if s.get("state_id") == state_id:
                return s
    # fallback: 按时间找最接近的
    best = None
    for s in sorted(states, key=lambda s: s.get("time_minute", 0)):
        if s.get("time_minute", 0) <= minute:
            best = s
    return best


def get_due_events(record: dict, advance_minutes: int, case_data: dict = None) -> list:
    """推进模拟时间并返回触发的事件列表"""
    state = record.get("timeline_state", {})
    current = state.get("current_simulated_minute", 0)
    new_minute = current + advance_minutes
    mode = record.get("mode", "practice")

    triggered = []
    for ev in state.get("timeline_events", []):
        if ev.get("triggered"):
            continue
        if ev.get("scheduled_minute", 0) <= new_minute:
            ev["triggered"] = True
            # 应用 patient_state
            if case_data and ev.get("patient_state_id"):
                ps = _get_patient_state(case_data, ev["patient_state_id"], new_minute)
                if ps:
                    state["current_patient_state_id"] = ps["state_id"]
                    state["current_patient_state"]["appearance"] = ps.get("appearance", "")
                    state["current_patient_state"]["expression"] = ps.get("chief_complaint", "")

            # 应用生命体征变化
            for vid, new_val in ev.get("vital_changes", {}).items():
                state.setdefault("current_vitals", {})[vid] = new_val

            # 复评标记
            if ev.get("requires_reassessment"):
                state["reassessment_due"] = True

            # 恶化标记
            if ev.get("event_type") == "deterioration":
                state["deteriorated"] = True

            # 模式控制: exam 隐藏提示
            result_ev = dict(ev)
            if mode in ("exam", "osce"):
                result_ev["student_prompt"] = ""
            triggered.append(result_ev)

    state["current_simulated_minute"] = new_minute

    # 检查复评是否逾期
    if state.get("reassessment_due") and not state.get("reassessment_completed"):
        due = state.get("next_reassessment_due", 30)
        if new_minute > due + 10:
            state["reassessment_overdue"] = True

    record["timeline_state"] = state
    return triggered


def apply_timeline_event(record: dict, event_id: str, case_data: dict = None) -> dict:
    """应用单个时间轴事件"""
    state = record.get("timeline_state", {})

    for ev in state.get("timeline_events", []):
        if ev["event_id"] == event_id:
            for vid, new_val in ev.get("vital_changes", {}).items():
                state.setdefault("current_vitals", {})[vid] = new_val

            state["current_patient_state"]["expression"] = ev.get("patient_expression", "")
            state["current_patient_state"]["last_event"] = event_id
            ev["triggered"] = True

            if case_data and ev.get("patient_state_id"):
                ps = _get_patient_state(case_data, ev["patient_state_id"])
                if ps:
                    state["current_patient_state_id"] = ps["state_id"]
                    state["current_patient_state"]["appearance"] = ps.get("appearance", "")

            break

    record["timeline_state"] = state
    return record


ANSWER_LIKE_EVENT_KEYS = {
    "expected_student_actions",
    "consequence_if_missed",
    "standard_level_after_event",
    "severe_error_if_ignored",
    "severe_error_code",
    "vital_changes",
    "trigger_condition",
}


def _natural_event_cue(ev: dict, mode: str = "practice") -> str:
    """Build a student-facing timeline cue without leaking the expected action."""
    expression = str(ev.get("patient_expression") or "").strip()
    description = str(ev.get("event_description") or "").strip()
    event_type = str(ev.get("event_type") or "")
    minute = ev.get("scheduled_minute", 0)

    if expression:
        if event_type == "deterioration":
            return f"候诊巡视时患者主动表示：{expression}"
        return f"候诊区患者反馈：{expression}"

    if description:
        text = description
        for token in ("Ⅱ级", "Ⅲ级", "Ⅰ级", "Ⅳ级", "红区", "黄区", "绿区", "升级", "必须", "立即"):
            text = text.replace(token, "")
        text = text.replace("HR", "心率").replace("BP", "血压").strip(" ，,。")
        if text:
            return f"第{minute}分钟患者状态出现变化：{text}"

    return f"第{minute}分钟候诊观察节点。"


def sanitize_timeline_events_for_mode(events: list, mode: str, current_minute: int | None = None) -> list:
    """Return student-facing events while keeping internal scoring metadata private."""
    safe = []
    for ev in events or []:
        scheduled = int(ev.get("scheduled_minute") or 0)
        triggered = bool(ev.get("triggered")) or (
            current_minute is not None and scheduled <= int(current_minute)
        )
        item = {
            "event_id": ev.get("event_id", ""),
            "scheduled_minute": scheduled,
            "event_type": ev.get("event_type", ""),
            "triggered": triggered,
        }

        if not triggered:
            item.update({
                "visible_to_student": False,
                "event_description": "待观察",
                "patient_expression": "",
                "student_prompt": "",
                "requires_reassessment": False,
            })
            safe.append(item)
            continue

        cue = _natural_event_cue(ev, mode)
        item.update({
            "visible_to_student": bool(ev.get("visible_to_student", True)),
            "event_description": cue,
            "patient_expression": ev.get("patient_expression", ""),
            "requires_reassessment": bool(ev.get("requires_reassessment")),
            "student_prompt": "" if mode in ("exam", "osce") else cue,
        })
        for key in ANSWER_LIKE_EVENT_KEYS:
            item.pop(key, None)
        safe.append(item)
    return safe


def sanitize_patient_state_for_mode(patient_state: dict, mode: str) -> dict:
    """P0-1: exam/osce 模式移除患者状态中的标准答案字段。"""
    if not patient_state:
        return patient_state
    if mode not in ("exam", "osce"):
        # practice 也移除标准答案，只保留学员可观察信息
        return _sanitize_patient_state_safe(patient_state)
    return _sanitize_patient_state_safe(patient_state)


def _sanitize_patient_state_safe(ps: dict) -> dict:
    """移除所有标准答案和答案化字段"""
    safe = dict(ps)
    for key in list(safe.keys()):
        if key.startswith("standard_") or key.startswith("expected_") or key.startswith("severe_error_"):
            safe.pop(key, None)
    safe.pop("recommended_actions", None)
    safe.pop("state_vitals", None)
    # vitals 只保留学员已测量的（按当前设计由前端按需获取）
    if "vitals" in safe and safe["vitals"]:
        # 保留为空 dict 或最小信息
        safe["vitals"] = {}
    return safe


def get_current_patient_state(record: dict, case_data: dict = None) -> dict:
    """获取当前患者状态（含 patient_states 数据）"""
    state = record.get("timeline_state", {})
    minute = state.get("current_simulated_minute", 0)
    ps = None
    if case_data:
        ps = _get_patient_state(case_data, state.get("current_patient_state_id"), minute)

    result = {
        "minute": minute,
        "stage": normalize_stage_value(state.get("current_stage", "ARRIVAL"), "ARRIVAL"),
        "expression": state.get("current_patient_state", {}).get("expression", ""),
        "appearance": state.get("current_patient_state", {}).get("appearance", ""),
        "vitals": state.get("current_vitals", {}),
        "next_reassessment_due": state.get("next_reassessment_due", 30),
        "reassessment_due": state.get("reassessment_due", False),
        "deteriorated": state.get("deteriorated", False),
    }

    if ps:
        result.update({
            "state_id": ps.get("state_id", ""),
            "patient_state_id": ps.get("state_id", ""),
            "state_name": ps.get("state_name", ""),
            "standard_triage_level": ps.get("standard_triage_level", ""),
            "standard_area": ps.get("standard_area", ""),
            "recommended_actions": ps.get("recommended_actions", []),
            "state_vitals": ps.get("vital_signs", {}),
        })

    return result


def get_current_vital_signs(record: dict, case_data: dict) -> dict:
    """获取当前时间点的生命体征（优先 patient_states，fallback required_measurements）"""
    state = record.get("timeline_state", {})
    minute = state.get("current_simulated_minute", 0)

    ps = _get_patient_state(case_data, state.get("current_patient_state_id"), minute)
    if ps and ps.get("vital_signs"):
        return ps["vital_signs"]

    # fallback: 从 required_measurements 取
    measurements = case_data.get("required_measurements", [])
    vital_map = {}
    for m in measurements:
        vid = m.get("id", "")
        val = m.get("value", "")
        vital_map[vid] = val
    return vital_map


def record_triage_decision(record: dict, decision_type: str, level: str, area: str = "",
                           reassessment_minutes: int = None, notify_doctor: bool = False,
                           reason: str = "") -> dict:
    """记录一次分诊决策到 record.triage_decisions"""
    state = record.get("timeline_state", {})
    minute = state.get("current_simulated_minute", 0)

    decision = {
        "decision_type": decision_type,  # "initial" or "reassessment"
        "simulation_minute": minute,
        "level": level,
        "area": area,
        "reassessment_minutes": reassessment_minutes,
        "notify_doctor": notify_doctor,
        "reason": reason,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    record.setdefault("triage_decisions", []).append(decision)

    # 同步 final_level_selected
    record["final_level_selected"] = level
    record["final_zone_selected"] = area

    if decision_type == "initial":
        state["initial_level_selected"] = level
        if reassessment_minutes:
            state["next_reassessment_due"] = reassessment_minutes

    record["timeline_state"] = state
    return record


def record_student_action(record: dict, action_type: str, detail: dict = None) -> dict:
    """写入 student_actions 日志"""
    from services.action_logger import log_student_action
    return log_student_action(record, action_type, detail)
