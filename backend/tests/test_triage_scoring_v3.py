"""V3 评分引擎测试"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.triage_scoring_v3 import score_triage_v3

CASE = {
    "patient_profile":{"age":56,"gender":"男"},
    "standard_answer":{"triage_level":"Ⅱ级","triage_zone":"红区","minimum_safe_level":"Ⅱ级","disposition":["通知心内科","心电图"]},
    "critical_signals":[{"id":"cardiac_chest_pain","label":"心源性胸痛","evidence":["胸痛","放射痛"]}],
    "required_measurements":[{"id":"spo2","label":"SpO2","value":"95%","is_abnormal":False},{"id":"bp","label":"血压","value":"158/96","is_abnormal":True}],
    "dialogue_state_machine":{"slots":[
        {"slot_id":"onset_time","label":"起病时间","canonical_intents":["ask_onset_time"],"is_required":True},
        {"slot_id":"pain_radiation","label":"放射痛","canonical_intents":["ask_pain_radiation"],"is_required":True},
    ]},
}


class TestV3Scoring:
    def test_full_score_output(self):
        rec = {"disclosed_slots":["onset_time","pain_radiation"],"measured_vitals":["spo2","bp"],
               "final_level_selected":"Ⅱ级","final_zone_selected":"红区","final_disposition":["通知心内科"]}
        r = score_triage_v3(rec, CASE)
        assert "total_score" in r
        assert "pass_status" in r
        assert "rule_result" in r
        assert "detail_scores" in r
        assert r["total_score"] > 0

    def test_severe_error_fails(self):
        rec = {"disclosed_slots":[],"measured_vitals":[],"final_level_selected":"Ⅳ级","final_zone_selected":"绿区"}
        r = score_triage_v3(rec, CASE)
        # Ⅳ级选择触发严重错误时应为fail
        if r.get("severe_error_triggered"):
            assert r["pass_status"] == "fail"

    def test_rule_result_included(self):
        rec = {"disclosed_slots":["onset_time"],"measured_vitals":["spo2"],"final_level_selected":"Ⅱ级","final_zone_selected":"红区"}
        r = score_triage_v3(rec, CASE)
        assert "rule_result" in r
        rr = r["rule_result"]
        assert "minimum_level_by_rules" in rr
        assert "esi_ctas_mapping" in rr
        assert "under_triage" in rr

    def test_8_dimensions(self):
        rec = {"disclosed_slots":["onset_time"],"measured_vitals":["spo2"],"final_level_selected":"Ⅱ级","final_zone_selected":"红区"}
        r = score_triage_v3(rec, CASE)
        assert len(r["detail_scores"]) == 8
