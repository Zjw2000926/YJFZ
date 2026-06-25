"""固定回复问题: 批量修复病例 dialogue_state_machine.slots 答案数据

1. 将重复主诉的 answer_facts 替换为维度特定的回答
2. 清除"根据病例资料回答。"占位文本
3. 去重 slot_id 重复映射

用法: python tools/fix_dialogue_data.py [--dry-run] [--case TRIAGE-006]
"""
import json, os, sys, argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "triage_data")
CASE_DIRS = ["cases", "cases_dynamic"]

# ── 每个维度一个合理模板，按 slot_id 的语义关键词匹配 ──
DIMENSION_TEMPLATES = {
    "chief_complaint": "{}",
    "onset_time": "大概{}开始的，持续了{}。",
    "trauma": "{}之后出现的，没有摔倒，也没有被撞。",
    "pain_location": "{}这一块疼。",
    "pain_nature": "是刺痛，按压会更痛。",
    "pain_radiation": "没有放射到其他部位。",
    "severity": "大概七八分，主要是局部不舒服。",
    "aggravating": "按压、活动时更痛，休息会好一些。",
    "accompanying": "没有恶心、出汗、晕厥，也没有明显气促。",
    "breathing": "呼吸还可以，没有明显喘不上气。",
    "consciousness": "意识清楚，没晕过去。",
    "past_history": "以前没有这方面的大毛病。",
    "medication": "平时没吃特殊药物。",
    "allergy": "没有明确药物过敏。",
    "smoking": "不抽烟，偶尔喝点酒。",
    "family": "没有家属陪同。",
}

PLACEHOLDER_TEXT = "根据病例资料回答。"


def categorize_slot(slot_id, label):
    """根据 slot_id 和 label 关键词返回维度类别"""
    combined = f"{slot_id} {label}".lower()
    if "chief" in combined or "主诉" in label or "哪里" in label:
        return "chief_complaint"
    if "onset" in combined or "时间" in label or "开始" in label or "多久" in label:
        return "onset_time"
    if "trauma" in combined or "诱因" in label or "原因" in label or "搬" in label or "扭" in label or "撞" in label:
        return "trauma"
    if "location" in combined or "位置" in label or "部位" in label:
        return "pain_location"
    if "nature" in combined or "性质" in label:
        return "pain_nature"
    if "radiation" in combined or "放射" in label:
        return "pain_radiation"
    if "severity" in combined or "严重" in label or "评分" in label or "pain_score" in combined:
        return "severity"
    if "aggravat" in combined or "缓解" in label or "加重" in label or "呼吸" in combined or "体位" in combined or "按压" in label:
        return "aggravating"
    if "accompany" in combined or "伴随" in label or "恶心" in label or "出汗" in label or "晕厥" in label:
        return "accompanying"
    if "breathing" in combined or "呼吸" in label or "气促" in label or "胸闷" in label:
        return "breathing"
    if "consciousness" in combined or "意识" in label or "头晕" in label or "晕厥" in label:
        return "consciousness"
    if "history" in combined or "既往" in label or "过去" in label or "病史" in label or "基础" in label:
        return "past_history"
    if "medication" in combined or "用药" in label or "药物" in label or "吃药" in label:
        return "medication"
    if "allergy" in combined or "过敏" in label:
        return "allergy"
    if "smoking" in combined or "烟" in label or "酒" in label:
        return "smoking"
    if "family" in combined or "家属" in label or "目睹" in label:
        return "family"
    return None


def generate_fact(slot_id, label, case_data):
    """根据维度分类 + 病例 clinical_information 生成合理的回答事实"""
    category = categorize_slot(slot_id, label)
    ci = case_data.get("clinical_information", {}) or {}
    positives = ci.get("key_positive_information", [])
    negatives = ci.get("key_negative_information", [])
    chief = case_data.get("initial_exposure", {}).get("chief_complaint", "")

    if category == "chief_complaint":
        return chief.strip('"') if chief else "就是这里不舒服。"
    if category == "onset_time":
        return "刚才开始的，大概十来分钟。"
    if category == "trauma":
        detail = next((p for p in positives if "搬" in p or "摔" in p or "碰" in p or "扭" in p), "")
        return detail if detail else "没有明显的外伤。"
    if category == "pain_location":
        detail = next((p for p in positives if "位置" in p or "部位" in p or "局部" in p), "")
        return detail if detail else "就在这一块疼。"
    if category == "pain_nature":
        return "是刺痛，按压会更痛。"
    if category == "pain_radiation":
        neg = next((n for n in negatives if "放射" in n), "")
        return neg if neg else "没有放射到其他部位。"
    if category == "severity":
        return "挺疼的，打个七八分吧。"
    if category == "aggravating":
        return "按压和活动时更痛，安静不动稍好。"
    if category == "accompanying":
        negs = [n for n in negatives if any(kw in n for kw in ["恶心","出汗","晕厥","大汗","气促"])]
        return "、".join(negs[:3]) + "。" if negs else "没有特别的其他不舒服。"
    if category == "breathing":
        return "呼吸还可以，没有明显喘不上气。"
    if category == "consciousness":
        return "意识清楚，没晕过去。"
    if category == "past_history":
        neg = next((n for n in negatives if "病" in n or "史" in n), "")
        return neg if neg else "平时身体还行，没什么大毛病。"
    if category == "medication":
        return "平时没吃特殊药物。"
    if category == "allergy":
        return "没有明确药物过敏。"
    if category == "smoking":
        return "不抽烟，偶尔喝点酒。"
    if category == "family":
        return "没有家属陪同。"
    return "这个我说不太清楚。"


def fix_slots(case_data):
    """修复病例的 dialogue_state_machine.slots"""
    state = case_data.get("dialogue_state_machine", {})
    slots = state.get("slots", [])
    chief = case_data.get("initial_exposure", {}).get("chief_complaint", "")
    opening = case_data.get("initial_exposure", {}).get("opening_line", "")

    fixed_count = 0
    for slot in slots:
        sid = slot.get("slot_id", "")
        label = slot.get("label", "")
        facts = slot.get("answer_facts", [])

        if not facts:
            slot["answer_facts"] = [generate_fact(sid, label, case_data)]
            fixed_count += 1
            continue

        first = str(facts[0]).strip() if facts else ""

        # 检查是否需要修复
        needs_fix = (
            not first
            or first == PLACEHOLDER_TEXT
            or first == f'"{PLACEHOLDER_TEXT}。"'
            or (first in (chief, opening, f'"{chief}"', f'"{opening}"') and "chief" not in sid.lower() and "主诉" not in label)
        )

        if needs_fix:
            slot["answer_facts"] = [generate_fact(sid, label, case_data)]
            fixed_count += 1

    return fixed_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--case", type=str, default=None, help="仅处理指定病例")
    args = parser.parse_args()

    total_fixed = 0
    files_fixed = 0

    for subdir in CASE_DIRS:
        d = os.path.join(BASE, subdir)
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".json"):
                continue
            if args.case and args.case not in fname:
                continue

            path = os.path.join(d, fname)
            with open(path, "r", encoding="utf-8") as f:
                case = json.load(f)

            n = fix_slots(case)
            if n > 0:
                total_fixed += n
                files_fixed += 1
                if not args.dry_run:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(case, f, ensure_ascii=False, indent=2)
                print(f"{'[DRY-RUN]' if args.dry_run else 'Fixed'} {fname}: {n} slots")

    print(f"\nFiles: {files_fixed}, Slots fixed: {total_fixed}")


if __name__ == "__main__":
    main()
