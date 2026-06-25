"""规则引擎数据结构"""

LEVEL_RANK = {"Ⅰ级": 1, "Ⅱ级": 2, "Ⅲ级": 3, "Ⅳ级": 4}
RANK_LEVEL = {1: "Ⅰ级", 2: "Ⅱ级", 3: "Ⅲ级", 4: "Ⅳ级"}

class RuleHit:
    def __init__(self, rule_id, level, category, evidence, source=None):
        self.rule_id = rule_id
        self.level = level
        self.category = category
        self.evidence = evidence
        self.source = source or []

    def to_dict(self):
        return {"rule_id":self.rule_id,"level":self.level,"category":self.category,
                "evidence":self.evidence,"source":self.source}

class RuleResult:
    def __init__(self):
        self.rule_set_version = "triage_rule_set_v1@1.0"
        self.minimum_level_by_rules = "Ⅳ级"
        self.final_standard_level = "Ⅳ级"
        self.recommended_zone = "绿区"
        self.esi_ctas_mapping = {"esi":5,"ctas":5}
        self.under_triage = False
        self.over_triage = False
        self.severe_error_triggered = False
        self.severe_error_codes = []
        self.rule_hits = []
        self.explanations = []

    def to_dict(self):
        return {
            "rule_set_version":self.rule_set_version,
            "minimum_level_by_rules":self.minimum_level_by_rules,
            "final_standard_level":self.final_standard_level,
            "recommended_zone":self.recommended_zone,
            "esi_ctas_mapping":self.esi_ctas_mapping,
            "under_triage":self.under_triage,
            "over_triage":self.over_triage,
            "severe_error_triggered":self.severe_error_triggered,
            "severe_error_codes":self.severe_error_codes,
            "rule_hits":[h.to_dict() for h in self.rule_hits],
            "explanations":self.explanations,
        }
