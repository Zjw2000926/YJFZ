"""Student action logging helpers."""

from datetime import datetime, timezone
from typing import Any


CRITICAL_ACTIONS = {
    "initial_triage",
    "set_reassessment_time",
    "reassess",
    "upgrade_triage",
    "notify_doctor",
    "record_note",
    "submit",
}


def log_student_action(
    record: dict[str, Any],
    action_type: str,
    detail: dict[str, Any] | None = None,
    *,
    is_required: bool | None = None,
    is_correct: bool | None = None,
    is_late: bool = False,
    score_delta: int | None = None,
    feedback: str = "",
) -> dict[str, Any]:
    state = record.get("timeline_state") or {}
    minute = state.get("current_simulated_minute", 0)
    action = {
        "action_type": action_type,
        "simulation_minute": minute,
        "detail": detail or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_key_action": action_type in CRITICAL_ACTIONS,
        "is_required": is_required,
        "is_correct": is_correct,
        "is_late": is_late,
        "score_delta": score_delta,
        "feedback": feedback,
    }
    record.setdefault("student_actions", []).append(action)
    state.setdefault("system_events", []).append({
        "event_type": action_type,
        "simulation_minute": minute,
        "detail": detail or {},
    })
    record["timeline_state"] = state
    return record

