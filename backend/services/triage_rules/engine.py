"""规则引擎总入口

输入：病例、学员行为、生命体征、最终选择
输出：RuleResult（含最低安全等级、严重错误、规则命中、ESI/CTAS映射）

纯函数式，不依赖 LLM，不依赖数据库查询。
"""

import json, os
from .models import RuleResult, RuleHit, LEVEL_RANK, RANK_LEVEL
from .vital_rules import evaluate_vitals
from .symptom_rules import evaluate_symptoms
from .special_population_rules import evaluate_special_population
from .severity import compare_levels
from .explanation import generate_explanations

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING_PATH = os.path.join(BASE, "triage_data", "mappings", "mapping_domestic_esi_ctas_v1.json")

_mapping_cache = None


def _load_mapping():
    global _mapping_cache
    if _mapping_cache is None:
        with open(MAPPING_PATH, encoding="utf-8") as f:
            _mapping_cache = json.load(f)
    return _mapping_cache


def evaluate(case_data: dict, record: dict) -> RuleResult:
    """规则引擎主入口。

    Args:
        case_data: 病例数据（含 required_measurements, critical_signals, standard_answer, patient_profile）
        record: 训练记录（含 disclosed_slots, measured_vitals, final_level_selected, final_zone_selected, intent_events）

    Returns:
        RuleResult（可通过 .to_dict() 序列化为 JSON）
    """
    result = RuleResult()
    all_hits = []

    # 1. 生命体征规则
    measurements = record.get("measured_vitals", [])
    # 从 case_data 重建测量结果
    req_ms = case_data.get("required_measurements", [])
    measured_data = []
    for mid in measurements:
        for m in req_ms:
            if m.get("id") == mid:
                measured_data.append(m)
                break

    vital_hits, vital_min = evaluate_vitals(measured_data, case_data)
    all_hits.extend(vital_hits)

    # 2. 高危症状规则
    disclosed = record.get("disclosed_slots", [])
    symptom_hits, symptom_min = evaluate_symptoms(case_data, disclosed, record)
    all_hits.extend(symptom_hits)

    # 3. 特殊人群
    special_pop = evaluate_special_population(case_data)

    # 4. 计算规则最低等级
    rule_min = "Ⅳ级"
    if special_pop.get("suggest_upgrade"):
        rule_min = special_pop.get("suggested_minimum_level", "Ⅳ级")

    # 取所有命中规则中最危重的等级
    for level_str in ["Ⅰ级", "Ⅱ级", "Ⅲ级", "Ⅳ级"]:
        from_rule = any(h.get("level") == level_str for h in all_hits if isinstance(h, dict))
        from_vital = vital_min == level_str
        from_symptom = symptom_min == level_str
        from_special = rule_min == level_str
        if from_rule or from_vital or from_symptom or from_special:
            result.minimum_level_by_rules = level_str
            break

    # 5. 标准答案
    standard = case_data.get("standard_answer", {})
    std_level = standard.get("triage_level", "Ⅳ级")
    std_zone = standard.get("triage_zone", "绿区")

    # 6. 等级比较
    student_level = record.get("final_level_selected", "Ⅳ级") or "Ⅳ级"
    sev = compare_levels(student_level, std_level, result.minimum_level_by_rules)

    result.final_standard_level = sev["final_standard_level"]
    result.under_triage = sev["under_triage"]
    result.over_triage = sev["over_triage"]

    # 7. 区域建议
    if LEVEL_RANK.get(result.final_standard_level, 4) <= 2:
        result.recommended_zone = "红区"
    elif LEVEL_RANK.get(result.final_standard_level, 4) == 3:
        result.recommended_zone = "黄区"
    else:
        result.recommended_zone = "绿区"

    # 8. ESI/CTAS 映射
    mapping = _load_mapping().get("mappings", {})
    mapped = mapping.get(result.final_standard_level, mapping.get("Ⅳ级", {}))
    result.esi_ctas_mapping = {"esi": mapped.get("esi", 5), "ctas": mapped.get("ctas", 5)}

    # 9. 严重错误
    severe_codes = []
    # 严重低估
    if sev["severe_error"]:
        severe_codes.append(f"SEVERE_UNDER_TRIAGE_{student_level}_TO_{result.final_standard_level}")

    # 从病例 standard_answer 中的 minimum_safe_level 检查
    min_safe = standard.get("minimum_safe_level", "")
    if min_safe and LEVEL_RANK.get(student_level, 4) > LEVEL_RANK.get(min_safe, 4):
        diff = LEVEL_RANK.get(student_level, 4) - LEVEL_RANK.get(min_safe, 4)
        if diff >= 2:
            severe_codes.append(f"BELOW_MINIMUM_SAFE_LEVEL_{min_safe}")

    if severe_codes:
        result.severe_error_triggered = True
        result.severe_error_codes = severe_codes

    # 10. 规则命中记录
    for h in all_hits:
        if isinstance(h, dict):
            result.rule_hits.append(RuleHit(
                rule_id=h.get("rule_id",""), level=h.get("level",""),
                category=h.get("category",""), evidence=h.get("evidence",""),
                source=h.get("source",[])))

    # 11. 解释生成
    result.explanations = generate_explanations(all_hits, sev, special_pop)

    return result
