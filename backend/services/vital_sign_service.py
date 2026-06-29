"""Vital sign lookup and interpretation for dynamic triage cases."""

from typing import Any

from services.triage_timeline import get_current_vital_signs


VITAL_ALIASES = {
    "heart_rate": ["heart_rate", "heart_rate_bpm"],
    "heart_rate_bpm": ["heart_rate", "heart_rate_bpm"],
    "respiratory_rate": ["respiratory_rate", "respiratory_rate_bpm"],
    "respiratory_rate_bpm": ["respiratory_rate", "respiratory_rate_bpm"],
    "spo2": ["spo2", "spo2_percent"],
    "spo2_percent": ["spo2", "spo2_percent"],
    "temperature": ["temperature", "temperature_c"],
    "temperature_c": ["temperature", "temperature_c"],
    "pain_score": ["pain_score", "nrs"],
    "consciousness": ["consciousness", "mental_status"],
    "gcs": ["gcs", "gcs_score"],
    "gcs_score": ["gcs_score", "gcs"],
    "blood_glucose": ["blood_glucose", "blood_glucose_mmol_l"],
    "blood_glucose_mmol_l": ["blood_glucose_mmol_l", "blood_glucose"],
    "skin_perfusion": ["skin_perfusion"],
    "mews": ["mews"],
}

NON_VITAL_MEASUREMENT_IDS = {"other_assessments", "history_items", "focused_history"}


def measure_multiple_vital_signs(record: dict[str, Any], case_data: dict[str, Any], item_ids: list[str]) -> list[dict[str, Any]]:
    current_vitals = get_current_vital_signs(record, case_data)
    label_map = {m["id"]: m.get("label", m["id"]) for m in case_data.get("required_measurements", [])}
    unit_map = {m["id"]: m.get("unit", "") for m in case_data.get("required_measurements", [])}

    measurements = []
    for item_id in item_ids:
        if item_id in NON_VITAL_MEASUREMENT_IDS:
            continue
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

    if item_id in {"heart_rate", "heart_rate_bpm"} and numeric is not None and (numeric >= 120 or numeric < 50):
        is_abnormal = True
        message = "心率明显异常，提示循环代偿或病情加重风险，需要结合症状变化复评。"
    elif item_id in {"respiratory_rate", "respiratory_rate_bpm"} and numeric is not None and (numeric >= 24 or numeric < 10):
        is_abnormal = True
        message = "呼吸频率异常，提示病情风险升高，需要结合SpO₂和意识状态判断紧急程度。"
    elif item_id in {"spo2", "spo2_percent"} and numeric is not None and numeric < 94:
        is_abnormal = True
        message = "SpO₂偏低，属于重要客观危险信号，应提高分诊警觉。"
    elif item_id in {"temperature", "temperature_c"} and numeric is not None and numeric >= 38.0:
        is_abnormal = True
        message = "体温升高，提示炎症或感染相关风险，需要结合主诉和生命体征趋势复评。"
    elif item_id == "pain_score" and numeric is not None and numeric >= 7:
        is_abnormal = True
        message = "疼痛评分较高或加重，应作为复评和分诊优先级判断的重要依据。"
    elif item_id == "blood_pressure" and isinstance(value, str) and "/" in value:
        try:
            sbp = float(value.split("/", 1)[0])
            if sbp < 100 or sbp >= 180:
                is_abnormal = True
                message = "血压超出安全观察范围或呈下降趋势，提示循环风险，需要及时复评。"
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
