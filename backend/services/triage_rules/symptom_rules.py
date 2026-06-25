"""高危症状规则"""

import json, os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES_PATH = os.path.join(BASE,"triage_data","rules","triage_rule_set_v1.json")

_cache = None

def _load():
    global _cache
    if _cache is None:
        with open(RULES_PATH,encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache

def evaluate_symptoms(case_data, disclosed_slots, record):
    """评估高危症状规则。"""
    from .models import LEVEL_RANK
    critical_signals = case_data.get("critical_signals",[])
    rule_set = _load()
    rules = rule_set.get("rules",[])
    hits = []
    min_level = "Ⅳ级"

    for rule in rules:
        cond = rule.get("conditions",{})
        matched = False
        evidence_parts = []

        # Check critical signals
        any_cs = cond.get("any_critical_signal",[])
        for cs_id in any_cs:
            for cs in critical_signals:
                if cs.get("id") == cs_id:
                    matched = True
                    evidence_parts.append(f"高危信号:{cs.get('label','')}")

        # Check disclosed slots
        any_slot = cond.get("any_slot_detected",[])
        if any_slot:
            ds = disclosed_slots or record.get("disclosed_slots",[])
            for sid in any_slot:
                if sid in ds:
                    matched = True
                    evidence_parts.append(f"已采集槽:{sid}")

        if matched:
            rl = rule.get("minimum_level","Ⅱ级")
            hr = {"rule_id":rule["rule_id"],"level":rl,"category":rule.get("category",""),
                  "evidence":rule.get("explanation","") + " " + ";".join(evidence_parts),
                  "source":evidence_parts}
            hits.append(hr)
            if LEVEL_RANK.get(rl,4) < LEVEL_RANK.get(min_level,4):
                min_level = rl

    return hits, min_level
