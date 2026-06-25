"""动态预检分诊患者状态机

定义状态枚举、转移规则、状态推进逻辑。
每个 action 触发状态转移，状态记录在 record.timeline_state.current_stage 中。
"""

from enum import Enum
from typing import Optional


class Stage(Enum):
    NOT_STARTED = "NOT_STARTED"
    ARRIVAL = "ARRIVAL"
    FIRST_LOOK = "FIRST_LOOK"
    HISTORY_TAKING = "HISTORY_TAKING"
    INITIAL_VITALS = "INITIAL_VITALS"
    INITIAL_TRIAGE = "INITIAL_TRIAGE"
    WAITING = "WAITING"
    REASSESSMENT_DUE = "REASSESSMENT_DUE"
    DETERIORATED = "DETERIORATED"
    REASSESSMENT = "REASSESSMENT"
    RE_TRIAGE = "RE_TRIAGE"
    FINAL_DISPOSITION = "FINAL_DISPOSITION"
    COMPLETED = "COMPLETED"


# 状态转移规则: {当前状态: {action: 下一状态}}
TRANSITIONS = {
    Stage.NOT_STARTED: {
        "start_training": Stage.ARRIVAL,
    },
    Stage.ARRIVAL: {
        "first_look": Stage.FIRST_LOOK,
        "start_history": Stage.HISTORY_TAKING,
        "measure_vitals": Stage.INITIAL_VITALS,
    },
    Stage.FIRST_LOOK: {
        "start_history": Stage.HISTORY_TAKING,
        "measure_vitals": Stage.INITIAL_VITALS,
    },
    Stage.HISTORY_TAKING: {
        "measure_vitals": Stage.INITIAL_VITALS,
        "first_look": Stage.HISTORY_TAKING,  # 可从问诊返回观察
    },
    Stage.INITIAL_VITALS: {
        "initial_triage": Stage.INITIAL_TRIAGE,
        "start_history": Stage.HISTORY_TAKING,  # 可回退补充问诊
    },
    Stage.INITIAL_TRIAGE: {
        "wait": Stage.WAITING,
        "advance_time": Stage.WAITING,
        "submit": Stage.COMPLETED,
    },
    Stage.WAITING: {
        "advance_time": Stage.WAITING,
        "reassessment_due": Stage.REASSESSMENT_DUE,
        "deteriorated": Stage.DETERIORATED,
        "reassess": Stage.REASSESSMENT,
        "submit": Stage.COMPLETED,
    },
    Stage.REASSESSMENT_DUE: {
        "reassess": Stage.REASSESSMENT,
        "re_triage": Stage.RE_TRIAGE,
        "deteriorated": Stage.DETERIORATED,
        "submit": Stage.COMPLETED,
    },
    Stage.DETERIORATED: {
        "reassess": Stage.REASSESSMENT,
        "re_triage": Stage.RE_TRIAGE,
        "submit": Stage.COMPLETED,
    },
    Stage.REASSESSMENT: {
        "re_triage": Stage.RE_TRIAGE,
        "notify_doctor": Stage.FINAL_DISPOSITION,
        "submit": Stage.COMPLETED,
    },
    Stage.RE_TRIAGE: {
        "notify_doctor": Stage.FINAL_DISPOSITION,
        "adjust_area": Stage.FINAL_DISPOSITION,
        "record_notes": Stage.FINAL_DISPOSITION,
        "submit": Stage.COMPLETED,
    },
    Stage.FINAL_DISPOSITION: {
        "record_notes": Stage.FINAL_DISPOSITION,
        "submit": Stage.COMPLETED,
    },
    Stage.COMPLETED: {},
}


def _coerce_stage(value) -> str:
    """兼容旧记录或迁移病例中误写入的非字符串阶段值。"""
    if isinstance(value, Stage):
        return value.value
    if isinstance(value, str) and value in Stage._value2member_map_:
        return value
    if value:
        return Stage.ARRIVAL.value
    return Stage.NOT_STARTED.value


class PatientStateMachine:
    """患者状态机，绑定到单次训练记录"""

    def __init__(self, record: dict):
        self.timeline = record.setdefault("timeline_state", {})
        # P0-2: 始终补齐必要字段，不只在空状态时创建
        self.timeline.setdefault("current_stage", Stage.NOT_STARTED.value)
        self.timeline["current_stage"] = _coerce_stage(self.timeline.get("current_stage"))
        self.timeline.setdefault("stage_history", [])
        self.timeline.setdefault("system_events", [])
        self.timeline.setdefault("current_simulated_minute", self.timeline.get("simulation_minute", 0))
        self.timeline.setdefault("reassessment_completed", False)
        self.timeline.setdefault("reassessment_overdue", False)
        self.timeline.setdefault("deteriorated", False)
        record["timeline_state"] = self.timeline

    @property
    def current_stage(self) -> str:
        stage = _coerce_stage(self.timeline.get("current_stage", Stage.NOT_STARTED.value))
        self.timeline["current_stage"] = stage
        return stage

    @property
    def simulation_minute(self) -> int:
        return self.timeline.get("current_simulated_minute", self.timeline.get("simulation_minute", 0))

    @property
    def reassessment_due(self) -> bool:
        return self.current_stage in (Stage.REASSESSMENT_DUE.value, Stage.DETERIORATED.value)

    @property
    def is_completed(self) -> bool:
        return self.current_stage == Stage.COMPLETED.value

    def transition(self, action: str) -> Optional[str]:
        """尝试状态转移，返回新状态或 None（不合法转移）"""
        current = Stage(self.current_stage) if self.current_stage else Stage.NOT_STARTED
        next_states = TRANSITIONS.get(current, {})
        next_stage = next_states.get(action)

        if next_stage is None:
            return None  # 不合法转移

        self._set_stage(next_stage, action)
        return next_stage.value

    def advance_time(self, minutes: int) -> dict:
        """推进模拟时间"""
        self.timeline["current_simulated_minute"] = self.simulation_minute + minutes
        return {
            "current_minute": self.simulation_minute,
            "advanced_by": minutes,
        }

    def mark_reassessment_due(self):
        """标记需要复评"""
        if self.current_stage in (Stage.WAITING.value, Stage.INITIAL_TRIAGE.value):
            self._set_stage(Stage.REASSESSMENT_DUE, "reassessment_due")
            self._add_event("REASSESSMENT_DUE_TRIGGERED")

    def mark_deteriorated(self):
        """标记病情恶化"""
        self._set_stage(Stage.DETERIORATED, "deteriorated")
        self.timeline["deteriorated"] = True
        self._add_event("DETERIORATION_DETECTED")

    def mark_reassessment_complete(self):
        """标记复评完成"""
        self.timeline["reassessment_completed"] = True

    def mark_reassessment_overdue(self):
        """标记复评逾期"""
        self.timeline["reassessment_overdue"] = True

    def add_doctor_notification(self):
        """记录通知医生"""
        self._add_event("DOCTOR_NOTIFIED")

    def _add_event(self, event_type: str, detail: dict = None):
        self.timeline.setdefault("system_events", []).append({
            "event_type": event_type,
            "simulation_minute": self.simulation_minute,
            "detail": detail or {},
        })

    def _set_stage(self, next_stage: Stage, action: str):
        prev = self.current_stage
        self.timeline["current_stage"] = next_stage.value
        if prev != next_stage.value or action in ("advance_time", "submit"):
            self.timeline.setdefault("stage_history", []).append({
                "from": prev,
                "to": next_stage.value,
                "action": action,
                "simulation_minute": self.simulation_minute,
            })

    def to_dict(self) -> dict:
        return dict(self.timeline)


def create_state_machine(record: dict) -> PatientStateMachine:
    """工厂函数：从 record 创建状态机"""
    sm = PatientStateMachine(record)
    # 如果尚未启动，自动从 ARRIVAL 开始
    if sm.current_stage == Stage.NOT_STARTED.value:
        sm.transition("start_training")
    return sm
