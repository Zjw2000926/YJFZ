"""病例对话数据校验脚本
Usage: python scripts/validate_triage_dialogue_data.py
"""
import json, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "triage_data")
CASE_DIRS = ["cases", "cases_dynamic"]

PLACEHOLDER = {"根据病例资料回答。", "根据病例资料回答", "根据病例资料回答该项内容。"}


def validate():
    issues = []
    for subdir in CASE_DIRS:
        d = os.path.join(BASE, subdir)
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(d, fname)
            with open(path, "r", encoding="utf-8") as f:
                case = json.load(f)

            cid = case.get("external_id", fname)
            initial = case.get("initial_exposure", {}) or {}
            chief = str(initial.get("chief_complaint", "")).strip().strip('"').strip("'")
            opening = str(initial.get("opening_line", "")).strip().strip('"').strip("'")

            state = case.get("dialogue_state_machine", {})
            slots = state.get("slots", [])

            if not slots:
                continue

            # Check 1: empty answer_facts
            for slot in slots:
                sid = slot.get("slot_id", "?")
                facts = slot.get("answer_facts") or []
                if not facts or not str(facts[0]).strip():
                    issues.append(f"[EMPTY] {cid} / {sid}: 无 answer_facts")

            # Check 2: placeholder answers
            for slot in slots:
                sid = slot.get("slot_id", "?")
                facts = slot.get("answer_facts") or []
                first = str(facts[0]).strip() if facts else ""
                if first in PLACEHOLDER:
                    issues.append(f"[PLACEHOLDER] {cid} / {sid}: {first[:40]}")

            # Check 3: non-chief slots duplicating chief/opening
            for slot in slots:
                sid = slot.get("slot_id", "?")
                if "chief" in sid.lower() or "主诉" in slot.get("label", ""):
                    continue
                facts = slot.get("answer_facts") or []
                first = str(facts[0]).strip().strip('"').strip("'") if facts else ""
                if first and (first == chief or first == opening):
                    issues.append(f"[DUP_CHIEF] {cid} / {sid}: = chief/opening line")

            # Check 4: same answer across >2 non-chief slots
            answer_counts = defaultdict(list)
            for slot in slots:
                sid = slot.get("slot_id", "?")
                if "chief" in sid.lower() or "主诉" in slot.get("label", ""):
                    continue
                facts = slot.get("answer_facts") or []
                first = str(facts[0]).strip() if facts else ""
                if first:
                    answer_counts[first].append(sid)
            for ans, sids in answer_counts.items():
                if len(sids) > 2:
                    issues.append(f"[DUPLICATE_{len(sids)}x] {cid}: same answer across slots {sids[:4]}")

    # Report
    if issues:
        print(f"=== 发现 {len(issues)} 个问题 ===")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("=== 全部通过 ✅ === 无占位答案、无重复主诉、无空 slot")

    return issues


if __name__ == "__main__":
    issues = validate()
    sys.exit(1 if issues else 0)
