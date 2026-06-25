"""V2 意图识别评测脚本
读取 triage_eval_intents.jsonl，调用意图识别器，输出准确率报告。

用法: python tools/eval_intents.py
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.triage_intent import recognize_intent

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_PATH = os.path.join(BASE, "triage_data", "triage_eval_intents.jsonl")


def load_eval(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def main():
    if not os.path.exists(EVAL_PATH):
        print(f"评测文件不存在: {EVAL_PATH}")
        return

    items = load_eval(EVAL_PATH)
    total = len(items)
    correct = 0
    failures = []

    for item in items:
        utterance = item["user_utterance"]
        expected = item.get("standard_intent", "")
        result = recognize_intent(utterance)
        predicted = result.get("intent", "") if result else ""

        if predicted == expected:
            correct += 1
        else:
            failures.append({
                "utterance": utterance[:40],
                "expected": expected,
                "predicted": predicted,
            })

    accuracy = correct / total * 100 if total > 0 else 0
    print(f"=== 意图识别评测 ===")
    print(f"样本数: {total}")
    print(f"正确数: {correct}")
    print(f"准确率: {accuracy:.1f}%")
    print(f"失败样例: {len(failures)}")
    for f in failures[:10]:
        print(f"  '{f['utterance']}' → 期望{f['expected']} 实际{f['predicted']}")

    # 写入报告
    report = {
        "total": total,
        "correct": correct,
        "accuracy_pct": round(accuracy, 1),
        "failures": failures,
    }
    report_path = os.path.join(BASE, "triage_data", "eval_intent_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已写入: {report_path}")


if __name__ == "__main__":
    main()
