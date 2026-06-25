"""等级比较：低估/高估判断"""

from .models import LEVEL_RANK, RANK_LEVEL

def compare_levels(student_level, standard_level, minimum_by_rules):
    """比较学生选择、标准答案、规则最低等级。

    Returns: {
        under_triage, over_triage, severe,
        level_diff, final_standard_level
    }
    """
    final_std = standard_level
    std_rank = LEVEL_RANK.get(final_std, 4)
    rule_rank = LEVEL_RANK.get(minimum_by_rules, 4)

    # 取更危重的作为最终标准
    if rule_rank < std_rank:
        final_std = minimum_by_rules

    student_rank = LEVEL_RANK.get(student_level, 4)
    final_rank = LEVEL_RANK.get(final_std, 4)

    under_triage = student_rank > final_rank  # 学生低估（数字大=危重程度低）
    over_triage = student_rank < final_rank   # 学生高估（数字小=危重程度高）
    level_diff = abs(student_rank - final_rank)

    # 严重低估：差2级或把Ⅰ/Ⅱ级判为Ⅳ级
    severe = (final_rank <= 2 and student_rank >= 4) or level_diff >= 2

    return {
        "student_level": student_level,
        "standard_level": standard_level,
        "minimum_by_rules": minimum_by_rules,
        "final_standard_level": final_std,
        "under_triage": under_triage,
        "over_triage": over_triage,
        "severe_error": severe,
        "level_diff": level_diff,
    }
