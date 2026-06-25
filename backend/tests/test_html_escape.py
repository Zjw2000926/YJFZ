"""P1-06 HTML escaping 测试
验证 build_html_report 对所有动态内容进行了 HTML 转义，
防止 XSS 攻击。
"""
import pytest
from services.triage_admin_repository import build_html_report


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
