"""P1-06 HTML escaping 测试
验证 build_html_report 对所有动态内容进行了 HTML 转义，
防止 XSS 攻击。
"""
import pytest
from services.triage_admin_repository import build_html_report, build_html_reports


def test_build_html_report_escapes_script_tags():
    """P1-06: 对话内容中的 <script> 标签应被转义"""
    record = {
        "total_score": 85,
        "pass_status": "good",
        "final_level_selected": "<script>alert(1)</script>",
        "final_zone_selected": "黄区",
        "score_detail": {"主诉采集": {"score": 12, "max": 15}},
        "timeline_state": {"timeline_events": []},
        "messages": [
            {"role": "student", "content": "<img src=x onerror=alert(1)>"},
            {"role": "patient", "content": "正常内容"},
        ],
    }
    html = build_html_report(record)

    # 原始危险标签的尖括号必须被转义（阻断标签解析）
    assert "<script>" not in html
    assert "<img" not in html
    # 转义后的内容应该出现
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html


def test_build_html_report_escapes_dimension_keys():
    """P1-06: 评分维度名称中的特殊字符应被转义"""
    record = {
        "total_score": 70,
        "pass_status": "pass",
        "final_level_selected": "Ⅲ级",
        "final_zone_selected": "绿区",
        "score_detail": {"<b>bold</b>": {"score": 10, "max": 15}},
        "timeline_state": {"timeline_events": []},
        "messages": [],
    }
    html = build_html_report(record)
    assert "<b>bold</b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html


def test_build_html_report_allows_normal_content():
    """P1-06: 正常内容应完好保留"""
    record = {
        "total_score": 90,
        "pass_status": "excellent",
        "final_level_selected": "Ⅰ级",
        "final_zone_selected": "红区",
        "score_detail": {"主诉采集": {"score": 14, "max": 15}},
        "timeline_state": {"timeline_events": []},
        "messages": [
            {"role": "student", "content": "请问您哪里不舒服？"},
            {"role": "patient", "content": "我胸口疼，喘不上气"},
        ],
    }
    html = build_html_report(record)
    assert "请问您哪里不舒服" in html
    assert "我胸口疼，喘不上气" in html
    assert "90" in html
    assert "excellent" in html


def test_build_html_reports_batches_multiple_records_and_escapes():
    """批量报告应合并多份报告，同时继续转义动态内容。"""
    records = [
        {
            "id": "r1",
            "total_score": 90,
            "pass_status": "excellent",
            "final_level_selected": "Ⅱ级",
            "final_zone_selected": "红区",
            "score_detail": {"主诉采集": {"score": 14, "max": 15}},
            "timeline_state": {"timeline_events": []},
            "messages": [{"role": "student", "content": "<script>alert(1)</script>"}],
        },
        {
            "id": "r2",
            "total_score": 76,
            "pass_status": "pass",
            "final_level_selected": "Ⅲ级",
            "final_zone_selected": "黄区",
            "score_detail": {"复评": {"score": 8, "max": 10}},
            "timeline_state": {"timeline_events": []},
            "messages": [],
        },
    ]
    html = build_html_reports(records)
    assert "预检分诊训练报告 #1" in html
    assert "预检分诊训练报告 #2" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_build_html_report_auto_print_is_opt_in():
    record = {
        "total_score": 85,
        "pass_status": "good",
        "final_level_selected": "Ⅱ级",
        "final_zone_selected": "红区",
        "score_detail": {},
        "timeline_state": {"timeline_events": []},
        "messages": [],
    }
    normal = build_html_report(record)
    printable = build_html_report(record, auto_print=True)
    assert "window.print" not in normal
    assert "window.print" in printable


def test_build_html_report_exports_full_student_report_sections():
    """PDF打印页应包含学员报告页的关键详细小节。"""
    record = {
        "id": "full-report-1",
        "user_display_name": "测试学员",
        "case_external_id": "TRIAGE-TEST",
        "mode": "practice",
        "started_at": "2026-06-28T08:00:00",
        "submitted_at": "2026-06-28T08:10:00",
        "total_score": 78,
        "effective_score": 78,
        "pass_status": "pass",
        "severe_error_triggered": False,
        "final_level_selected": "Ⅱ级",
        "final_zone_selected": "红区",
        "final_disposition": ["notify_doctor"],
        "standard_answer": {
            "triage_level": "Ⅱ级",
            "triage_zone": "红区",
            "disposition": ["立即通知医生", "优先处置"],
        },
        "timeline_report": {
            "case_type": "dynamic",
            "is_dynamic_case": True,
            "standard_initial_level": "Ⅲ级",
            "standard_initial_area": "黄区",
            "student_initial_level": "Ⅲ级",
            "student_initial_area": "黄区",
            "standard_final_level": "Ⅱ级",
            "standard_final_area": "红区",
            "student_final_level": "Ⅱ级",
            "student_final_area": "红区",
            "reassessment_on_time": True,
            "reassessment_reasonable": True,
            "deterioration_recognized": True,
            "triage_upgraded": True,
            "doctor_notified": True,
            "timeline_nodes": [
                {"label": "T30", "minute": 30, "event": "患者面色苍白、冷汗", "stage": "DETERIORATED", "student_action": "主动复评"},
            ],
            "action_timeline": [
                {"minute": 30, "action_type": "reassess", "detail": {"note": "重新测量生命体征"}, "is_correct": True},
            ],
            "vital_measurement_log": [
                {"simulation_minute": 30, "result": {"heart_rate": 122, "blood_pressure": "96/60"}},
            ],
        },
        "score_detail": {
            "复评内容完成": {
                "score": 8,
                "max": 10,
                "summary": "已完成复评但记录略少",
                "deduction_reasons": ["复评说明不足"],
                "evidence": ["重新测量心率和血压"],
                "standard_basis": "动态病例恶化后必须复评。",
                "international_reference": "参考ESI/CTAS复评原则。",
                "improvement": "记录症状变化和异常报告。",
                "criteria": [
                    {
                        "label": "病情变化后重新测量生命体征",
                        "score": 4,
                        "max_score": 4,
                        "met": True,
                        "evidence": "T30重新测量HR/BP",
                        "standard_basis": "复评需重新获得客观指标。",
                    }
                ],
            }
        },
        "criterion_scores": [
            {
                "criterion": "通知医生",
                "score": 2,
                "max_score": 2,
                "met": True,
                "evidence": ["notify_doctor"],
                "missed_reason": "",
                "teaching_point": "恶化后立即通知医生。",
            }
        ],
        "score_explanations": [
            {"name": "复评内容完成", "score": 8, "max": 10, "summary": "过程基本完整", "deduction_reasons": ["记录略少"]},
        ],
        "feedback": {
            "correct_points": ["能识别恶化并升级"],
            "risk_if_missed": ["延误处理"],
            "key_red_flag": ["冷汗", "血压下降"],
            "reason_for_triage_level": "T30出现低血压趋势和疼痛加重，应升级为Ⅱ级。",
            "missed_required_questions": ["用药史"],
            "recommended_remediation": ["复评记录训练"],
            "feedback_evidence": {
                "basis": "基于对话、操作和生命体征记录。",
                "covered_items": ["疼痛加重", "冷汗"],
                "measured_items": ["heart_rate", "blood_pressure"],
            },
        },
        "messages": [
            {"role": "student", "content": "现在疼痛有没有加重？"},
            {"role": "patient", "content": "更疼了，头有点晕，还出冷汗。"},
        ],
        "actions": [
            {"action_type": "notify_doctor", "payload": {"reason": "T30恶化"}, "created_at": "2026-06-28T08:08:00"},
        ],
    }
    html = build_html_report(record)
    for section in ["分诊决策对比", "训练流程概览", "分项评分", "评分证据明细", "专家反馈", "训练对话记录"]:
        assert section in html
    for label in ["扣分点", "操作证据", "标准依据", "改进建议", "已完成证据"]:
        assert label in html
    for detail in ["患者面色苍白、冷汗", "T30重新测量HR/BP", "T30出现低血压趋势", "更疼了，头有点晕"]:
        assert detail in html
