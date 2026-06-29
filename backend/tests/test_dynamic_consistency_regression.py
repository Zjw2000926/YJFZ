from services.feedback_evidence import detect_record_groups
from services.scoring_engine import score_case
from services.triage_repository import get_case
from services.triage_timeline import (
    get_current_patient_state,
    get_due_events,
    initialize_timeline,
    record_triage_decision,
)
from services.vital_sign_service import measure_multiple_vital_signs


L1 = "\u2160\u7ea7"
L2 = "\u2161\u7ea7"
L3 = "\u2162\u7ea7"
RED = "\u7ea2\u533a"
YELLOW = "\u9ec4\u533a"
GREEN = "\u7eff\u533a"


def _dynamic_chest_record():
    case = get_case("TRIAGE-002")
    record = {
        "id": "dynamic-chest-regression",
        "case_external_id": "TRIAGE-002",
        "mode": "practice",
        "messages": [],
        "student_actions": [],
        "actions": [],
        "measured_vitals": [],
        "vital_measurement_log": [],
    }
    initialize_timeline(record, case)
    return case, record


def _measure_map(record, case, ids):
    return {item["id"]: item["value"] for item in measure_multiple_vital_signs(record, case, ids)}


def _dimension(score, dimension_id):
    return next(dim for dim in score["detail_scores"].values() if dim.get("dimension_id") == dimension_id)


def test_dynamic_chest_vitals_are_cumulative_at_each_timeline_node():
    case, record = _dynamic_chest_record()
    ids = ["heart_rate_bpm", "blood_pressure", "spo2_percent", "pain_score", "other_assessments"]

    t0 = _measure_map(record, case, ids)
    assert t0["heart_rate_bpm"] == 96
    assert t0["blood_pressure"] == "158/92"
    assert t0["pain_score"] == 6
    assert "other_assessments" not in t0

    get_due_events(record, 8, case)
    t8 = _measure_map(record, case, ids)
    assert t8["heart_rate_bpm"] == 112
    assert t8["blood_pressure"] == "158/92"
    assert t8["pain_score"] == 8

    get_due_events(record, 7, case)
    t15 = _measure_map(record, case, ids)
    assert t15["heart_rate_bpm"] == 112
    assert t15["blood_pressure"] == "92/60"
    assert t15["pain_score"] == 8


def test_dynamic_chest_patient_state_follows_timeline_minutes_without_explicit_state_id():
    case, record = _dynamic_chest_record()

    get_due_events(record, 8, case)
    t8_state = get_current_patient_state(record, case)
    assert t8_state["state_id"] == "T8_event_1"
    assert t8_state["expression"] == "胸痛加重至8/10，出汗增加，HR 112次/分。"

    get_due_events(record, 7, case)
    t15_state = get_current_patient_state(record, case)
    assert t15_state["state_id"] == "T15_event_2"
    assert t15_state["expression"] == "头晕，BP降至92/60 mmHg，面色苍白。"
    assert t15_state["expression"] != t8_state["expression"]


def test_current_patient_state_self_corrects_stale_state_id_by_current_minute():
    case, record = _dynamic_chest_record()
    record["timeline_state"]["current_simulated_minute"] = 15
    record["timeline_state"]["current_patient_state_id"] = "T0_initial"

    state = get_current_patient_state(record, case)

    assert state["state_id"] == "T15_event_2"
    assert "BP降至92/60" in state["expression"]


def test_patient_answers_do_not_award_history_question_credit():
    record = {
        "messages": [
            {"role": "student", "content": "你哪里不舒服？"},
            {"role": "patient", "content": "我有高血压和糖尿病，吃降压药，没有药物过敏。"},
        ],
        "intent_events": [{"intent": "ask_chief_complaint"}],
    }
    groups = detect_record_groups(record)
    assert "chief_complaint_location" in groups
    assert "history_risk" not in groups
    assert "medication" not in groups
    assert "allergy" not in groups


def test_level_one_yellow_area_is_serious_error_for_all_dynamic_cases():
    case, record = _dynamic_chest_record()
    record_triage_decision(record, "initial", L2, area="专病绿色通道", reassessment_minutes=10)
    get_due_events(record, 15, case)
    record_triage_decision(record, "reassessment", L1, area=YELLOW, notify_doctor=True)

    score = score_case(record, case)
    assert score["serious_error_triggered"] is True
    assert "LEVEL_AREA_MISMATCH_LEVEL1" in score["serious_error_codes"]
    disposition = _dimension(score, "disposition")
    assert disposition["score"] < disposition["max"]


def test_notify_in_final_submit_only_is_not_timely_after_deterioration():
    case, record = _dynamic_chest_record()
    record_triage_decision(record, "initial", L2, area="专病绿色通道", reassessment_minutes=10)
    get_due_events(record, 15, case)
    record_triage_decision(record, "reassessment", L1, area=RED, notify_doctor=False)
    record["final_disposition"] = ["notify_doctor"]

    score = score_case(record, case)
    assert (
        "NO_DOCTOR_NOTIFICATION_AFTER_WORSENING" in score["serious_error_codes"]
        or "NO_DOCTOR_NOTIFICATION" in score["serious_error_codes"]
    )
    disposition = _dimension(score, "disposition")
    notify = next(item for item in disposition["criteria"] if item["id"] == "notify")
    assert notify["score"] == 0
    assert "通知医生" in notify["deduction_reason"]


def test_standard_level_controls_reassessment_interval_not_student_mislevel():
    case, record = _dynamic_chest_record()
    record_triage_decision(record, "initial", L3, area=GREEN, reassessment_minutes=30)
    score = score_case(record, case)
    reassessment_time = _dimension(score, "reassessment_time")
    reasonable = next(item for item in reassessment_time["criteria"] if item["id"] == "reasonable_interval")
    assert reasonable["score"] < reasonable["max"]
    assert "10分钟" in reasonable["evidence"]
