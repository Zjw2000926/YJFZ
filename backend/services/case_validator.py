"""Validation for triage case JSON data.

The validator is intentionally pure and side-effect free. Repository loading can
attach the result to a case or tests can call it directly before a case is used.
"""

from collections import Counter
import json
from typing import Any

from services.case_types import (
    CASE_TYPES,
    DYNAMIC_CASE,
    get_case_id,
    get_case_type,
    get_patient_states,
    get_standard_final_level,
    get_standard_initial_level,
    get_timeline_events,
    is_dynamic_case,
)


def validate_case(case_data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    dynamic_profile: dict[str, Any] = {}

    case_id = get_case_id(case_data)
    if not case_id:
        errors.append("case_id/external_id is required")

    case_type = get_case_type(case_data)
    if case_type not in CASE_TYPES:
        errors.append(f"case_type must be static or dynamic, got {case_type!r}")

    if is_dynamic_case(case_data):
        dynamic_profile = _validate_dynamic_case(case_data, errors, warnings)
    else:
        _validate_static_case(case_data, errors, warnings)

    result = {
        "valid": not errors,
        "case_id": case_id,
        "case_type": case_type,
        "errors": errors,
        "warnings": warnings,
    }
    if dynamic_profile:
        result["dynamic_profile"] = dynamic_profile
    return result


def validate_case_or_raise(case_data: dict[str, Any]) -> dict[str, Any]:
    result = validate_case(case_data)
    if result["errors"]:
        joined = "; ".join(result["errors"])
        raise ValueError(f"case validation failed for {result.get('case_id')}: {joined}")
    return result


def _validate_dynamic_case(case_data: dict[str, Any], errors: list[str], warnings: list[str]) -> dict[str, Any]:
    states = get_patient_states(case_data)
    events = get_timeline_events(case_data)

    if len(states) < 2:
        errors.append("dynamic case must have at least two patient_states")
    if len(events) < 1:
        errors.append("dynamic case must have at least one timeline event")

    state_ids = [s.get("state_id") for s in states if s.get("state_id")]
    event_ids = [e.get("event_id") for e in events if e.get("event_id")]
    _check_duplicates("state_id", state_ids, errors)
    _check_duplicates("event_id", event_ids, errors)

    state_id_set = set(state_ids)
    state_by_minute = {s.get("time_minute"): s.get("state_id") for s in states if s.get("time_minute") is not None and s.get("state_id")}
    implicit_refs = set()
    for event in events:
        sid = event.get("patient_state_id")
        if not sid:
            minute = event.get("scheduled_minute")
            inferred = state_by_minute.get(minute)
            if inferred:
                implicit_refs.add(inferred)
                warnings.append(f"timeline event {event.get('event_id', '<missing>')} missing patient_state_id; inferred {inferred} by scheduled_minute")
            else:
                errors.append(f"timeline event {event.get('event_id', '<missing>')} missing patient_state_id")
        elif sid not in state_id_set:
            errors.append(f"timeline event {event.get('event_id')} references missing patient_state_id {sid}")

    state_minutes = []
    for state in states:
        sid = state.get("state_id", "<missing>")
        minute = state.get("time_minute")
        if minute is None:
            errors.append(f"patient_state {sid} missing time_minute")
        else:
            state_minutes.append(minute)
        if not state.get("vital_signs"):
            errors.append(f"patient_state {sid} missing vital_signs")
        if not state.get("standard_triage_level"):
            errors.append(f"patient_state {sid} missing standard_triage_level")

    event_minutes = [e.get("scheduled_minute") for e in events if e.get("scheduled_minute") is not None]
    if state_minutes and state_minutes != sorted(state_minutes):
        errors.append("patient_states must be ordered by time_minute")
    if event_minutes and event_minutes != sorted(event_minutes):
        errors.append("timeline events must be ordered by scheduled_minute")

    if not get_standard_initial_level(case_data):
        errors.append("dynamic case missing standard_initial_triage_level")
    if not get_standard_final_level(case_data):
        errors.append("dynamic case missing standard_final_triage_level")

    if not case_data.get("dynamic_scoring_rubric") and not case_data.get("scoring_rubric"):
        errors.append("dynamic case missing scoring_rubric/dynamic_scoring_rubric")
    if not (case_data.get("dynamic_severe_errors") or case_data.get("serious_errors") or case_data.get("severe_errors")):
        errors.append("dynamic case missing serious_errors/dynamic_severe_errors")
    if not (case_data.get("required_dynamic_actions") or case_data.get("required_actions")):
        errors.append("dynamic case missing required_actions/required_dynamic_actions")

    if states and events:
        reachable = {events[0].get("patient_state_id")}
        reachable.add(states[0].get("state_id"))
        referenced = {e.get("patient_state_id") for e in events if e.get("patient_state_id")} | implicit_refs
        unreachable = sorted(set(state_ids) - reachable - referenced)
        if unreachable:
            warnings.append(f"unreachable patient_state ids: {', '.join(unreachable)}")

    profile = _build_dynamic_profile(states, events)
    if profile["timeline_node_count"] >= 2 and not profile["has_state_change"] and not profile["has_vital_change"]:
        warnings.append("dynamic case has multiple timeline nodes but no observable patient-state or vital-sign changes")
    elif profile["timeline_node_count"] >= 2 and not profile["has_vital_change"]:
        warnings.append("dynamic case has timeline/state changes but vital signs do not change across patient_states")
    return profile


def _build_dynamic_profile(states: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    state_keys = ("appearance", "chief_complaint", "symptom_description", "mental_status", "pain_score", "risk_signals")
    state_signatures = {
        json.dumps({key: state.get(key) for key in state_keys}, ensure_ascii=False, sort_keys=True)
        for state in states
    }
    vital_signatures = {
        json.dumps(state.get("vital_signs") or {}, ensure_ascii=False, sort_keys=True)
        for state in states
    }
    has_state_change = len(state_signatures) > 1
    has_vital_change = len(vital_signatures) > 1
    has_deterioration_event = any((event.get("event_type") or "").lower() in {"deterioration", "critical_change"} for event in events)
    standard_levels = [state.get("standard_triage_level") for state in states if state.get("standard_triage_level")]
    has_level_change = len(set(standard_levels)) > 1
    if has_deterioration_event or has_level_change:
        dynamic_subtype = "deterioration"
    elif has_state_change or has_vital_change:
        dynamic_subtype = "stable_reassessment"
    else:
        dynamic_subtype = "timeline_only"
    return {
        "timeline_node_count": len(states),
        "event_count": len(events),
        "has_state_change": has_state_change,
        "has_vital_change": has_vital_change,
        "has_level_change": has_level_change,
        "has_deterioration_event": has_deterioration_event,
        "dynamic_subtype": dynamic_subtype,
    }


def _validate_static_case(case_data: dict[str, Any], errors: list[str], warnings: list[str]):
    if not case_data.get("standard_answer"):
        warnings.append("static case missing standard_answer")
    if not case_data.get("required_measurements"):
        warnings.append("static case missing required_measurements")


def _check_duplicates(field: str, values: list[str], errors: list[str]):
    counts = Counter(values)
    dupes = sorted(v for v, count in counts.items() if count > 1)
    if dupes:
        errors.append(f"duplicate {field}: {', '.join(dupes)}")
