"""规则命中→反馈文本"""

def generate_explanations(rule_hits, severity_result, special_pop):
    """生成规则解释文本列表"""
    explanations = []

    # 从规则命中中提取解释
    for hit in rule_hits:
        if isinstance(hit, dict):
            evidence = hit.get("evidence", "")
            if evidence and evidence not in explanations:
                explanations.append(evidence)
        else:
            ev = getattr(hit, "evidence", "")
            if ev and ev not in explanations:
                explanations.append(ev)

    # 严重错误解释
    if severity_result.get("severe_error"):
        student = severity_result.get("student_level", "?")
        final = severity_result.get("final_standard_level", "?")
        explanations.append(f"学员选择{student}，规则要求最低{final}，属于严重低估分诊。")

    # 低/高估解释
    if severity_result.get("under_triage") and not severity_result.get("severe_error"):
        explanations.append(f"学员分诊等级偏低，建议注意高危信号识别。")
    if severity_result.get("over_triage"):
        explanations.append(f"学员分诊等级偏高，属于过度分诊，应注意资源合理分配。")

    # 特殊人群
    for hint in special_pop.get("hints", []):
        if hint not in str(explanations):
            explanations.append(f"特殊人群提醒: {hint}。")

    return explanations


def generate_feedback_text(rule_result, case_data):
    """生成教学反馈文本"""
    parts = []

    parts.append(f"规则引擎版本: {rule_result.get('rule_set_version','')}。")
    parts.append(f"规则最低安全等级: {rule_result.get('minimum_level_by_rules','')}。")

    if rule_result.get("severe_error_triggered"):
        parts.append("严重错误触发——一票否决。")
        for code in rule_result.get("severe_error_codes", []):
            parts.append(f"  严重错误: {code}")

    if rule_result.get("under_triage"):
        parts.append("存在低估分诊风险。")
    if rule_result.get("over_triage"):
        parts.append("存在过度分诊，请关注急诊资源合理使用。")

    std_fb = case_data.get("standard_feedback", {})
    if std_fb.get("summary"):
        parts.append(std_fb["summary"])

    return "\n".join(parts)
