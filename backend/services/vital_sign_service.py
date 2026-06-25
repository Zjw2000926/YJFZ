"""Vital sign lookup and interpretation for dynamic triage cases."""

from typing import Any

from services.triage_timeline import get_current_vital_signs


VITAL_ALIASES = {
    "heart_rate": ["heart_rate", "heart_rate_bpm"],
    "respiratory_rate": ["respiratory_rate", "respiratory_rate_bpm"],
    "spo2": ["spo2", "spo2_percent"],
    "temperature": ["temperature", "temperature_c"],
    "pain_score": ["pain_score", "nrs"],
    "consciousness": ["consciousness", "mental_status"],
    "gcs": ["gcs"],
    "blood_glucose": ["blood_glucose"],
    "mews": ["mews"],
}


def measure_multiple_vital_signs(record: dict[str, Any], case_data: dict[str, Any], item_ids: list[str]) -> list[dict[str, Any]]:
    current_vitals = get_current_vital_signs(record, case_data)
    label_map = {m["id"]: m.get("label", m["id"]) for m in case_data.get("required_measurements", [])}
    unit_map = {m["id"]: m.get("unit", "") for m in case_data.get("required_measurements", [])}

    measurements = []
    for item_id in item_ids:
        value = measure_vital_sign(item_id, current_vitals)
        if value is None:
            value = _fallback_required_measurement(case_data, item_id)
        interpretation = explain_vital_sign_abnormality(item_id, value)
        unit = unit_map.get(item_id, "")
        measurements.append({
            "id": item_id,
            "label": label_map.get(item_id, item_id),
            "value": value if value is not None else "--",
            "unit": unit,
            "display_value": f"{value}{unit}" if value is not None else "--",
            "is_abnormal": interpretation["is_abnormal"],
            "interpretation": interpretation["message"],
        })
    return measurements


def measure_vital_sign(item_id: str, vital_signs: dict[str, Any]) -> Any:
    if item_id == "blood_pressure":
        sbp = vital_signs.get("blood_pressure_systolic") or vital_signs.get("systolic_bp_mmhg")
        dbp = vital_signs.get("blood_pressure_diastolic") or vital_signs.get("diastolic_bp_mmhg")
        if sbp is not None and dbp is not None:
            return f"{_format_number(sbp)}/{_format_number(dbp)}"

    for alias in VITAL_ALIASES.get(item_id, [item_id]):
        if vital_signs.get(alias) is not None:
            return vital_signs.get(alias)
    return vital_signs.get(item_id)


def get_required_vital_signs_for_current_state(record: dict[str, Any], case_data: dict[str, Any]) -> list[str]:
    state = record.get("timeline_state") or {}
    if state.get("deteriorated"):
        return state.get("reassessment_required_items") or ["heart_rate", "blood_pressure", "pain_score", "respiratory_rate"]
    return [m.get("id") for m in case_data.get("required_measurements", []) if m.get("id")]


def detect_abnormal_vitals(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in measurements if m.get("is_abnormal")]


def explain_vital_sign_abnormality(item_id: str, value: Any) -> dict[str, Any]:
    numeric = _to_number(value)
    is_abnormal = False
    message = ""

    if item_id == "heart_rate" and numeric is not None and (numeric >= 120 or numeric < 50):
        is_abnormal = True
        message = "Heart rate is outside the expected triage range."
    elif item_id == "respiratory_rate" and numeric is not None and (numeric >= 24 or numeric < 10):
        is_abnormal = True
        message = "Respiratory rate suggests increased risk and needs reassessment."
    elif item_id == "spo2" and numeric is not None and numeric < 94:
        is_abnormal = True
        message = "SpO2 is low and should influence triage priority."
    elif item_id == "temperature" and numeric is not None and numeric >= 38.0:
        is_abnormal = True
        message = "Fever may support an acute inflammatory or infectious process."
    elif item_id == "pain_score" and numeric is not None and numeric >= 7:
        is_abnormal = True
        message = "Severe or worsening pain requires focused reassessment."
    elif item_id == "blood_pressure" and isinstance(value, str) and "/" in value:
        try:
            sbp = float(value.split("/", 1)[0])
            if sbp < 100 or sbp >= 180:
                is_abnormal = True
                message = "Blood pressure is outside the expected triage range."
        except ValueError:
            pass

    return {"is_abnormal": is_abnormal, "message": message}


def _fallback_required_measurement(case_data: dict[str, Any], item_id: str) -> Any:
    for measurement in case_data.get("required_measurements", []):
        if measurement.get("id") == item_id:
            return measurement.get("value")
    return None


def _to_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: Any) -> str:
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    except (TypeError, ValueError):
        return str(value)

