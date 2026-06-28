# -*- coding: utf-8 -*-

from services.feedback_evidence import (
    build_feedback_evidence,
    filter_missed_measurements,
    filter_missed_red_flags,
    filter_missed_slots,
)
from services.triage_repository import get_case
from services.triage_scoring_real_rubric import score_triage_real_rubric


L1 = "\u2160\u7ea7"
RED = "\u7ea2\u533a"


def _covered_chest_pain_record():
    return {
        "id": "feedback-evidence-chest-pain",
        "case_external_id": "TRIAGE-001",
        # Deliberately leave disclosed_slots empty: the feedback layer must not
        # mistake a slot matcher miss for a learner omission when the dialogue
        # contains the evidence.
        "disclosed_slots": [],
        "intent_events": [],
        "messages": [
            {"role": "student", "content": "你哪里不舒服？"},
            {"role": "patient", "content": "护士，我胸口压得特别厉害，喘不上气，整个人都很难受。"},
            {"role": "student", "content": "具体多久了？什么时候开始胸痛的？"},
            {"role": "patient", "content": "就是刚才开始的，大概十来分钟吧，突然胸口压得厉害。"},
            {"role": "student", "content": "胸口具体哪个部位？疼痛性质是什么样的？"},
            {"role": "patient", "content": "就是胸口这一片，像有块大石头压在胸口上，闷闷的。"},
            {"role": "student", "content": "有没有放射到肩背、左臂或者下颌？"},
            {"role": "patient", "content": "没有，就是胸口这里闷得慌，没有往肩背或者别的地方去。"},
            {"role": "student", "content": "有没有出汗、恶心、晕厥或者呼吸困难？"},
            {"role": "patient", "content": "有，心慌得厉害，身上出了一层冷汗，喘不上来气，差点晕过去。"},
            {"role": "student", "content": "有心脏病、高血压、糖尿病或者抽烟史吗？"},
            {"role": "patient", "content": "有高血压和糖尿病，一直吃着药，控制得不太好。平时也抽烟。"},
            {"role": "student", "content": "具体吃的什么药？最近稳定吗？"},
            {"role": "patient", "content": "就是降压药和降糖药，名字记不清了，最近总觉得胸口闷。"},
            {"role": "student", "content": "有什么药物过敏吗？"},
            {"role": "patient", "content": "没有，我以前没发现对什么药过敏。"},
            {"role": "student", "content": "以前有过类似发作吗？"},
            {"role": "patient", "content": "以前没有这么严重过，这次特别难受。"},
            {"role": "student", "content": "家属有没有补充？"},
            {"role": "patient", "content": "我妻子说我路上出了很多汗，还差点晕倒。"},
        ],
        "measured_vitals": [
            "blood_pressure",
            "heart_rate_bpm",
            "respiratory_rate_bpm",
            "spo2_percent",
            "pain_score",
            "consciousness",
        ],
        "final_level_selected": L1,
        "final_zone_selected": RED,
        "final_disposition": ["notify_doctor", "activate_green_channel"],
        "triage_reason": "胸痛伴低血压、冷汗、气促、SpO2下降，考虑高危胸痛，立即红区并通知医生。",
    }


def test_expert_feedback_uses_dialogue_text_not_only_disclosed_slots():
    case = get_case("TRIAGE-001")
    record = _covered_chest_pain_record()

    missed_questions = filter_missed_slots(case, record, record["disclosed_slots"])
    missed_text = "\n".join(missed_questions)

    assert "胸痛开始时间" not in missed_text
    assert "起病时间" not in missed_text
    assert "主诉/哪里不舒服" not in missed_text
    assert "大汗、恶心、 晕厥、气促" not in missed_text
    assert "既往冠心病、高血压、糖尿病、吸烟史" not in missed_text
    assert "有类似发作" not in missed_text
    assert "过敏史" not in missed_text
    assert "烟酒史" not in missed_text


def test_expert_feedback_measurement_aliases_and_red_flags_are_conversation_aware():
    case = get_case("TRIAGE-001")
    record = _covered_chest_pain_record()

    missed_measurements = filter_missed_measurements(case.get("required_measurements", []), record, record["measured_vitals"])
    missed_red_flags = filter_missed_red_flags(case.get("red_flags", []), record, record["measured_vitals"])
    missed_text = "\n".join(missed_measurements + missed_red_flags)

    assert "SpO" not in missed_text
    assert "胸痛伴低血压" not in missed_text
    assert "大汗和濒死感" not in missed_text


def test_real_rubric_feedback_does_not_list_covered_dialogue_as_omitted():
    case = get_case("TRIAGE-001")
    record = _covered_chest_pain_record()

    score = score_triage_real_rubric(record, case)
    feedback = score["feedback"]
    missed_text = "\n".join(
        feedback.get("missed_required_questions", [])
        + feedback.get("missed_measurements", [])
        + feedback.get("missed_red_flags", [])
    )

    assert feedback["feedback_version"] == "conversation_evidence_v1"
    assert feedback["feedback_evidence"]["covered_items"]
    assert "胸痛开始时间" not in missed_text
    assert "大汗、恶心、 晕厥、气促" not in missed_text
    assert "既往冠心病、高血压、糖尿病、吸烟史" not in missed_text
    assert "SpO" not in missed_text
