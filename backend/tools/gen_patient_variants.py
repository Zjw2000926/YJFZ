"""P1-1: 为病例自动生成患者表达变体
为每个病例补充 patient_variants（标准/口语/含糊焦虑三类），
以及 proxy_mode、emotional_state、forbidden_disclosure 等字段。

用法: python tools/gen_patient_variants.py [--dry-run]
"""
import json, os, sys, argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "triage_data")
CASE_DIRS = ["cases", "cases_dynamic"]


def gen_variants(case):
    """根据病例数据生成三类患者表达变体"""
    pp = case.get("patient_profile", {})
    ie = case.get("initial_exposure", {})
    chief = ie.get("chief_complaint", "")
    opening = ie.get("opening_line", "")

    gender = pp.get("gender", "")
    age = pp.get("age", "")
    appearance = pp.get("appearance", "")

    variants = []

    # 变体1: 标准表达（已有的开场白）
    variants.append({
        "variant_id": "standard",
        "label": "标准表达",
        "opening_line": opening,
        "tone": "neutral",
        "description": "患者标准叙述",
    })

    # 变体2: 口语化表达
    colloquial_openings = {
        "胸痛": "哎哟，我这胸口疼得厉害，像压了块石头似的...",
        "头痛": "我这头啊，疼得不行不行的，跟要炸了一样...",
        "发热": "我浑身发烫，冷得直打哆嗦，一点劲儿都没有...",
        "腹痛": "我肚子疼，疼得直不起腰来，您快帮我看看...",
        "呼吸困难": "我喘不上气，憋得慌，快闷死了...",
        "外伤": "我刚才不小心摔了一下，腿都肿了，疼死我了...",
    }
    colloquial_opening = ""
    for kw, txt in colloquial_openings.items():
        if kw in chief or kw in opening:
            colloquial_opening = txt
            break
    if not colloquial_opening:
        colloquial_opening = opening + " 反正就是特别难受，我也不知道咋形容。"

    variants.append({
        "variant_id": "colloquial",
        "label": "口语化表达",
        "opening_line": colloquial_opening,
        "tone": "colloquial",
        "description": "患者口语化、断续表达",
    })

    # 变体3: 含糊/焦虑表达
    variants.append({
        "variant_id": "anxious_vague",
        "label": "含糊/焦虑表达",
        "opening_line": f"医生...我、我也不知道怎么说，就是特别不舒服，我害怕是不是什么大病...",
        "tone": "anxious",
        "description": "患者焦虑、表达含糊、信息不完整",
    })

    return variants


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="仅检查，不写入")
    args = parser.parse_args()

    updated_count = 0

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

            # 跳过已有多个变体的病例
            existing = case.get("patient_variants", [])
            if len(existing) >= 3:
                continue

            case["patient_variants"] = gen_variants(case)
            case["emotional_state"] = "anxious" if "急" in case.get("display_name", "") else "neutral"
            case["proxy_mode"] = {"enabled": True if int(str(case.get("patient_profile", {}).get("age", 99)).split("岁")[0] if isinstance(case.get("patient_profile", {}).get("age", "0"), str) and "岁" in str(case.get("patient_profile", {}).get("age", "0")) else case.get("patient_profile", {}).get("age", 0)) <= 14 or int(str(case.get("patient_profile", {}).get("age", 99)).split("岁")[0] if isinstance(case.get("patient_profile", {}).get("age", "0"), str) and "岁" in str(case.get("patient_profile", {}).get("age", "0")) else case.get("patient_profile", {}).get("age", 0)) >= 75 else False, "proxy_type": "family_member"}
            case.setdefault("unclear_expression_mode", {"enabled": True, "trigger_on_reask": 2})
            case.setdefault("forbidden_disclosure", ["diagnosis", "exam_results", "consultation_conclusion"])
            case.setdefault("allowed_disclosure_by_stage", {"initial": ["chief_complaint", "onset", "basic_info"], "questioning": ["symptoms", "history", "medication", "allergy"], "assessment": ["vitals", "observations"]})

            if not args.dry_run:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(case, f, ensure_ascii=False, indent=2)
            updated_count += 1
            print(f"{'[DRY-RUN]' if args.dry_run else 'Updated'}: {fname}")

    print(f"\nTotal files processed: {updated_count}")


if __name__ == "__main__":
    main()
