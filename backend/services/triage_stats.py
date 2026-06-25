"""V5 预检分诊统计服务

指标：
- 分诊准确率 / 危重症识别率 / 低估分诊率 / 过度分诊率
- 关键问题采集率 / 生命体征完整率 / 复评完成率
- 绿色通道启动正确率 / 平均完成时间 / 沟通记录合格率
"""

import os, json
from datetime import datetime, timezone
from services.triage_repository import RECORDS_DIR


def _all_records():
    """获取所有训练记录"""
    records = []
    if not os.path.isdir(RECORDS_DIR):
        return records
    for fn in os.listdir(RECORDS_DIR):
        if fn.endswith(".json"):
            with open(os.path.join(RECORDS_DIR, fn), encoding="utf-8") as f:
                records.append(json.load(f))
    return records


def get_overview():
    """总览统计"""
    records = _all_records()
    scored = [r for r in records if r.get("total_score") is not None]

    total = len(records)
    scored_count = len(scored)
    avg_score = round(sum(r.get("total_score", 0) for r in scored) / max(scored_count, 1), 1)

    # 准确率
    correct = sum(1 for r in scored if r.get("pass_status") in ("excellent", "good", "pass"))
    accuracy = round(correct / max(scored_count, 1), 2)

    # 低估分诊
    under = sum(1 for r in scored if r.get("severe_error_triggered"))
    under_rate = round(under / max(scored_count, 1), 2)

    # 危重症识别 (Ⅰ/Ⅱ级正确)
    critical_correct = sum(1 for r in scored
                           if r.get("final_level_selected") in ("Ⅰ级", "Ⅱ级")
                           and not r.get("severe_error_triggered"))
    critical_rate = round(critical_correct / max(scored_count, 1), 2)

    # 复评完成率 (动态病例)
    dyn = [r for r in scored if r.get("is_dynamic")]
    reassess_done = sum(1 for r in dyn if len(r.get("timeline_state", {}).get("reassessments", [])) > 0)
    reassess_rate = round(reassess_done / max(len(dyn), 1), 2)

    # P2-1: 生命体征完整率 (基于每个病例真实required_measurements)
    vitals_measured = 0
    vitals_required = 0
    for r in scored:
        case_id = r.get("case_external_id", "")
        case = None
        try:
            from services.triage_repository import get_case
            case = get_case(case_id)
        except: pass
        req_ms = case.get("required_measurements", []) if case else []
        vitals_measured += len([m for m in req_ms if m.get("id") in r.get("measured_vitals", [])])
        vitals_required += len(req_ms)
    vital_rate = round(vitals_measured / max(vitals_required, 1), 2)

    # 平均时间
    times = []
    for r in scored:
        try:
            st = datetime.fromisoformat(r.get("started_at", "").replace("Z", "+00:00"))
            sb = datetime.fromisoformat(r.get("submitted_at", "").replace("Z", "+00:00"))
            times.append((sb - st).total_seconds() / 60)
        except:
            pass
    avg_time = round(sum(times) / max(len(times), 1), 1)

    # Pass distribution
    pass_dist = {"excellent": 0, "good": 0, "pass": 0, "fail": 0}
    for r in scored:
        ps = r.get("pass_status", "fail")
        if ps in pass_dist: pass_dist[ps] += 1
    pass_distribution = [{"name": k, "value": v} for k, v in pass_dist.items()]

    return {
        "total_records": total,
        "scored_records": scored_count,
        "avg_score": avg_score,
        "triage_accuracy": accuracy,
        "critical_recognition_rate": critical_rate,
        "under_triage_rate": under_rate,
        "reassessment_rate": reassess_rate,
        "vital_completeness": vital_rate,
        "avg_completion_minutes": avg_time,
        "recent_trend": _daily_trend(scored),
        "error_types": _error_breakdown(scored),
        "pass_distribution": pass_distribution,
    }


def get_student_stats(user_id=None):
    """学员个人统计"""
    records = _all_records()
    if user_id:
        records = [r for r in records if r.get("user_id") == user_id]

    scored = [r for r in records if r.get("total_score") is not None]
    n = len(scored)

    if n == 0:
        return {"user_id": user_id, "summary": {"total_records": 0}, "weaknesses": [], "recommended_practice": []}

    avg = round(sum(r.get("total_score", 0) for r in scored) / n, 1)
    correct = sum(1 for r in scored if r.get("pass_status") in ("excellent", "good", "pass"))
    under = sum(1 for r in scored if r.get("severe_error_triggered"))

    # 最近5次趋势
    recent = sorted(scored, key=lambda r: r.get("started_at", ""), reverse=True)[:5]
    trend = [r.get("total_score") for r in recent if r.get("total_score") is not None]

    # 高频漏问
    weaknesses = []
    missed_slots = {}
    for r in scored:
        required = len(r.get("disclosed_slots", []))
        total_slots = required + 3  # estimate
        if total_slots > 0 and required / total_slots < 0.5:
            missed_slots[r.get("case_external_id", "")] = missed_slots.get(r.get("case_external_id", ""), 0) + 1
    for cid, count in sorted(missed_slots.items(), key=lambda x: -x[1])[:3]:
        weaknesses.append({"type": cid, "label": f"{cid}信息采集不足", "miss_rate": round(count / n, 2)})

    # 推荐补训
    recommended = []
    if under / max(n, 1) > 0.2:
        recommended.append({"case_category": "高危病例", "reason": "低估分诊率偏高，建议加强Ⅰ/Ⅱ级病例训练"})
    if not weaknesses:
        pass
    else:
        for w in weaknesses[:2]:
            recommended.append({"case_category": w["type"], "reason": w["label"]})

    return {
        "user_id": user_id,
        "summary": {
            "total_records": n,
            "avg_score": avg,
            "triage_accuracy": round(correct / n, 2),
            "critical_recognition_rate": round(correct / n, 2),
            "under_triage_rate": round(under / n, 2),
            "recent_trend": trend,
        },
        "weaknesses": weaknesses,
        "recommended_practice": recommended,
    }


def _daily_trend(scored):
    """按日统计趋势"""
    by_date = {}
    for r in scored:
        try:
            st = r.get("started_at", "")[:10]
            if st not in by_date:
                by_date[st] = {"count": 0, "total_score": 0}
            by_date[st]["count"] += 1
            by_date[st]["total_score"] += r.get("total_score", 0)
        except:
            pass
    return [{"date": d, "count": v["count"], "avg_score": round(v["total_score"] / v["count"], 1)}
            for d, v in sorted(by_date.items())[-30:]]


def _error_breakdown(scored):
    """错误类型统计"""
    errors = {}
    for r in scored:
        for se in r.get("severe_error_codes", []):
            code = se if isinstance(se, str) else se.get("code", str(se))
            errors[code] = errors.get(code, 0) + 1
    return [{"code": k, "count": v} for k, v in sorted(errors.items(), key=lambda x: -x[1])[:10]]
