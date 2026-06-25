"""特殊人群风险上调规则"""

from .models import LEVEL_RANK

def evaluate_special_population(case_data):
    """评估特殊人群是否需要上调分诊等级。"""
    import re
    profile = case_data.get("patient_profile",{})
    age = profile.get("age",0)
    # P0-1 fix: handle string age like "58岁"
    if isinstance(age, str):
        m = re.search(r'(\d+)', str(age))
        age = int(m.group(1)) if m else 0
    gender = profile.get("gender","")

    population = {
        "elderly": age >= 65,
        "child": age <= 14,
        "pregnant_possible": False,
        "suicide_or_violence_risk": False,
        "infection_exposure_risk": False,
        "pediatric_seizure_risk": False,
    }

    # 检查病例高危信号
    for cs in case_data.get("critical_signals",[]):
        csid = cs.get("id","")
        if csid in ("suicide_risk", "violence_risk", "agitation"):
            population["suicide_or_violence_risk"] = True
        if csid in ("infection_exposure", "tb_exposure", "covid_exposure", "fever_unknown"):
            population["infection_exposure_risk"] = True
        if csid in ("pediatric_seizure", "febrile_convulsion"):
            population["pediatric_seizure_risk"] = True

    # 育龄女性可能妊娠
    if "女" in str(gender) and 15 <= age <= 49:
        population["pregnant_possible"] = True

    hints = []
    up_level = "Ⅳ级"

    if population["elderly"]:
        hints.append("老年患者(>=65岁)")
        up_level = "Ⅱ级"
    if population["child"]:
        hints.append("儿童患者(<=14岁)")
    if population["suicide_or_violence_risk"]:
        hints.append("自杀/暴力风险")
        up_level = "Ⅱ级" if LEVEL_RANK.get(up_level,4) > 2 else up_level
    if population["pregnant_possible"]:
        hints.append("育龄女性(需排除妊娠)")
    if population["infection_exposure_risk"]:
        hints.append("疑似传染病暴露(需隔离评估)")
        up_level = "Ⅱ级" if LEVEL_RANK.get(up_level,4) > 2 else up_level
    if population["pediatric_seizure_risk"] and population["child"]:
        hints.append("儿童惊厥风险(需紧急评估)")

    return {
        "population": population,
        "hints": hints,
        "suggest_upgrade": len(hints) > 0,
        "suggested_minimum_level": up_level if len(hints) > 0 else "Ⅳ级",
    }
