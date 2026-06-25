"""Shared case schema helpers for static and dynamic triage cases."""

from typing import Any


STATIC_CASE = "static"
DYNAMIC_CASE = "dynamic"
CASE_TYPES = {STATIC_CASE, DYNAMIC_CASE}


def get_case_id(case_data: dict[str, Any]) -> str:
    return case_data.get("case_id") or case_data.get("external_id") or ""


def is_dynamic_case(case_data: dict[str, Any]) -> bool:
    timeline = case_data.get("dynamic_timeline") or {}
    return bool(case_data.get("is_dynamic") or timeline.get("enabled"))


def get_case_type(case_data: dict[str, Any]) -> str:
    case_type = case_data.get("case_type")
    if case_type in CASE_TYPES:
        return case_type
    return DYNAMIC_CASE if is_dynamic_case(case_data) else STATIC_CASE


def get_patient_states(case_data: dict[str, Any]) -> list[dict[str, Any]]:
    states = case_data.get("patient_states") or []
    return states if isinstance(states, list) else []


def get_timeline_events(case_data: dict[str, Any]) -> list[dict[str, Any]]:
    timeline = case_data.get("dynamic_timeline") or {}
    events = timeline.get("events") or case_data.get("timeline_events") or []
    return events if isinstance(events, list) else []


def get_standard_initial_level(case_data: dict[str, Any]) -> str:
    return (
        case_data.get("standard_initial_triage_level")
        or (case_data.get("standard_answer") or {}).get("triage_level")
        or ""
    )


def get_standard_final_level(case_data: dict[str, Any]) -> str:
    return case_data.get("standard_final_triage_level") or get_standard_initial_level(case_data)


def get_standard_initial_area(case_data: dict[str, Any]) -> str:
    return (
        case_data.get("standard_initial_area")
        or (case_data.get("standard_answer") or {}).get("triage_zone")
        or ""
    )


def get_standard_final_area(case_data: dict[str, Any]) -> str:
    return case_data.get("standard_final_area") or get_standard_initial_area(case_data)

