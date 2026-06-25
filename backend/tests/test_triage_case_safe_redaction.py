"""P0-B test: verify get_case_safe redaction"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_safe_no_answers():
    from services.triage_repository import get_case_safe
    safe = get_case_safe("TRIAGE-001")
    assert safe is not None
    assert "required_measurements" not in safe, "should not have measurement values"
    assert "measurement_options" in safe, "should have measurement_options"
    for m in safe.get("measurement_options", []):
        assert "value" not in m
    assert "standard_answer" not in safe
    assert "scoring_rubric" not in safe
    assert "red_flags" not in safe
    assert "critical_errors" not in safe
    assert "assessment_checklist" not in safe

def test_safe_dynamic():
    from services.triage_repository import get_case_safe
    safe = get_case_safe("TRIAGE-002")
    assert safe is not None
    dt = safe.get("dynamic_timeline") or {}
    assert "events" not in dt, "dynamic events should not be in safe"
    assert dt.get("enabled") == True
    assert dt.get("has_dynamic_events") == True


def test_safe_dynamic_mvp_no_leak():
    """P0-1: get_case_safe 不泄露动态敏感字段"""
    from services.triage_repository import get_case_safe
    safe = get_case_safe("TRIAGE-DYN-RLQ-001")
    assert safe is not None
    sensitive = [
        "standard_initial_triage_level", "standard_final_triage_level",
        "standard_initial_area", "standard_final_area",
        "dynamic_scoring_rubric", "dynamic_severe_errors",
        "dynamic_feedback", "required_dynamic_actions",
        "standard_answer", "scoring_rubric", "feedback",
    ]
    for key in sensitive:
        assert key not in safe, f"leaked: {key}"
    # patient_states 只保留 id/minute/appearance
    ps = safe.get("patient_states", [])
    for s in ps:
        allowed = {"state_id", "time_minute", "appearance"}
        extra = set(s.keys()) - allowed
        assert not extra, f"patient_state leaked: {extra}"
        assert "standard_triage_level" not in s
        assert "standard_area" not in s
        assert "recommended_actions" not in s
        assert "vital_signs" not in s


def test_safe_has_options():
    from services.triage_repository import get_case_safe
    safe = get_case_safe("TRIAGE-001")
    assert "observation_options" in safe
    assert len(safe["observation_options"]) > 0
    assert "training_focus" in safe
