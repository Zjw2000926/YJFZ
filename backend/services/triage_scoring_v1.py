"""预检分诊 V1 评分引擎

基于记录事件评分，不调用 LLM。
严重错误一票否决。

评分维度（100 分制）：
- 主诉与起病时间采集：15
- 关键伴随症状追问：15
- 生命体征测量：15
- 高危信号识别：20
- 分诊等级判断：20
- 就诊区域与初步处置：10
- 沟通与记录：5
"""


def score_triage_record(record: dict, case_data: dict) -> dict:
    """对训练记录进行评分。

    Args:
        record: 训练记录（含 messages, actions, asked_questions 等）
        case_data: 病例数据（含标准答案和评分项）

    Returns:
        评分结果 dict
    """
    asked = record.get("asked_questions", [])
    measured = record.get("measured_vitals", [])
    final_level = record.get("final_level_selected")
    final_zone = record.get("final_zone_selected")

    required_qs = case_data.get("required_questions", [])
    required_ms = case_data.get("required_measurements", [])
    standard = case_data.get("standard_answer", {})
    critical_signals = case_data.get("critical_signals", [])
    severe_errors = case_data.get("severe_errors", [])

    total_questions = len(required_qs)
    total_measurements = len(required_ms)
    asked_count = len(asked)
    measured_count = len(measured)

    # === 1. 主诉与起病时间采集 (15分) ===
    chief_score = 0
    chief_items = []
    for qid in ["onset_time"]:
        if qid in asked:
            chief_score = 15
            chief_items.append({"id": qid, "score": 15, "evidence": "已询问起病时间"})
        else:
            chief_items.append({"id": qid, "score": int(15 * asked_count / max(total_questions, 1)),
                               "evidence": "未专门询问起病时间" if asked_count < 1 else "部分采集"})

    # === 2. 关键伴随症状追问 (15分) ===
    symptom_score = min(15, int(15 * (asked_count - 1) / max(total_questions - 1, 1))) if asked_count > 1 else 0
    symptom_items = [{"id": "symptoms", "score": symptom_score,
                      "evidence": f"追问了 {asked_count - 1} 项伴随信息" if asked_count > 1 else "未追问伴随症状"}]

    # === 3. 生命体征测量 (15分) ===
    abnormal_ms = [m for m in required_ms if m.get("is_abnormal")]
    vital_score = min(15, int(15 * measured_count / max(total_measurements, 1)))
    vital_items = [{"id": "vitals", "score": vital_score,
                    "evidence": f"测量了 {measured_count}/{total_measurements} 项生命体征"}]

    # === 4. 高危信号识别 (20分) ===
    cs_score = 0
    cs_items = []
    if critical_signals:
        # 检查是否问到了高危信号相关的关键问题
        cs_keywords_in_asked = False
        for cs in critical_signals:
            evidence_texts = " ".join(cs.get("evidence", []))
            for q in required_qs:
                if q.get("id") in asked:
                    for kw in q.get("keywords", []):
                        if kw in evidence_texts or any(
                            kw in e for e in cs.get("evidence", [])
                        ):
                            cs_score = 20
                            cs_keywords_in_asked = True
                            break
            if cs_keywords_in_asked:
                cs_items.append({"id": cs.get("id"), "score": 20,
                                "evidence": f"已识别高危信号: {cs.get('label')}"})
                break
        if not cs_keywords_in_asked:
            cs_items.append({"id": "critical", "score": 0, "evidence": "未充分识别高危信号"})
    else:
        cs_score = 20
        cs_items.append({"id": "critical", "score": 20, "evidence": "无高危信号需要识别"})

    # === 5. 分诊等级判断 (20分) ===
    std_level = standard.get("triage_level", "")
    if final_level == std_level:
        level_score = 20
        level_evidence = f"分诊等级 {final_level} 正确"
    else:
        # 差一级扣10分
        level_diff = _level_diff(final_level, std_level)
        level_score = max(0, 20 - level_diff * 10)
        level_evidence = f"选择了 {final_level}，标准答案为 {std_level}"

    # === 6. 就诊区域与初步处置 (10分) ===
    std_zone = standard.get("triage_zone", "")
    zone_score = 5 if final_zone and _zone_match(final_zone, std_zone) else 0
    zone_evidence = f"选择了 {final_zone}，标准为 {std_zone}"
    disposition = record.get("final_disposition", [])
    disp_score = min(5, len(disposition))
    zone_items = [
        {"id": "zone", "score": zone_score, "evidence": zone_evidence},
        {"id": "disposition", "score": disp_score, "evidence": f"处置项: {disposition}"},
    ]

    # === 7. 沟通与记录 (5分) ===
    msg_count = len(record.get("messages", []))
    comm_score = min(5, int(5 * (asked_count + 1) / max(total_questions + 2, 1)))
    comm_items = [{"id": "communication", "score": comm_score,
                    "evidence": f"共 {msg_count} 条对话记录"}]

    # === 汇总 ===
    detail_scores = {
        "主诉与起病时间采集": {"score": chief_score, "max": 15, "items": chief_items},
        "关键伴随症状追问": {"score": symptom_score, "max": 15, "items": symptom_items},
        "生命体征测量": {"score": vital_score, "max": 15, "items": vital_items},
        "高危信号识别": {"score": cs_score, "max": 20, "items": cs_items},
        "分诊等级判断": {"score": level_score, "max": 20,
                          "items": [{"id": "level", "score": level_score, "evidence": level_evidence}]},
        "就诊区域与初步处置": {"score": zone_score + disp_score, "max": 10, "items": zone_items},
        "沟通与记录": {"score": comm_score, "max": 5, "items": comm_items},
    }

    total_score = sum(d["score"] for d in detail_scores.values())

    # === 严重错误检测 ===
    triggered_severe = []
    for se in severe_errors:
        code = se.get("code", "")
        condition = se.get("condition", "")
        if _check_severe_error(condition, final_level, final_zone, cs_score):
            triggered_severe.append({"code": code, "message": se.get("message", "")})

    severe_triggered = len(triggered_severe) > 0

    # 一票否决：触发严重错误 → 不合格
    if severe_triggered:
        pass_status = "fail"
    elif total_score >= 90:
        pass_status = "excellent"
    elif total_score >= 80:
        pass_status = "good"
    elif total_score >= 60:
        pass_status = "pass"
    else:
        pass_status = "fail"

    # === 反馈 ===
    feedback = _generate_feedback(detail_scores, triggered_severe, case_data)

    return {
        "total_score": total_score,
        "pass_status": pass_status,
        "severe_error_triggered": severe_triggered,
        "severe_errors": triggered_severe,
        "detail_scores": detail_scores,
        "standard_answer": {
            "triage_level": standard.get("triage_level"),
            "triage_zone": standard.get("triage_zone"),
            "disposition": standard.get("disposition", []),
        },
        "feedback": feedback,
    }


def _level_diff(selected: str, standard: str) -> int:
    """计算分诊等级差异"""
    levels = {"Ⅰ级": 0, "Ⅱ级": 1, "Ⅲ级": 2, "Ⅳ级": 3}
    s = levels.get(selected, 3)
    t = levels.get(standard, 0)
    return abs(s - t)


def _zone_match(selected: str, standard: str) -> bool:
    """检查区域是否匹配（允许一定灵活性）"""
    if not selected or not standard:
        return False
    s = selected.strip()
    t = standard.strip()
    if s == t:
        return True
    if s in t or t in s:
        return True
    # 红区/黄区/绿区 简写
    zones = {"红区": "red", "黄区": "yellow", "绿区": "green",
             "red": "红区", "yellow": "黄区", "green": "绿区"}
    return zones.get(s) == zones.get(t)


def _check_severe_error(condition: str, final_level: str, final_zone: str,
                        cs_score: int) -> bool:
    """检查严重错误条件（简单规则评估）"""
    if not condition:
        return False
    # 简化规则评估
    if "final_level_selected == 'Ⅳ级'" in condition and final_level == "Ⅳ级":
        return True
    if "final_level_selected == 'Ⅲ级' or final_level_selected == 'Ⅳ级'" in condition:
        if final_level in ("Ⅲ级", "Ⅳ级"):
            return True
    if "final_level_selected == 'Ⅰ级' or final_level_selected == 'Ⅱ级'" in condition:
        if final_level in ("Ⅰ级", "Ⅱ级"):
            return True
    if "critical_signal_not_identified" in condition and cs_score < 10:
        return True
    return False


def _generate_feedback(detail_scores: dict, severe_errors: list,
                       case_data: dict) -> dict:
    """生成反馈内容"""
    strengths = []
    weaknesses = []
    missed = []

    for dim_name, dim_data in detail_scores.items():
        score = dim_data["score"]
        max_score = dim_data["max"]
        if score >= max_score * 0.8:
            strengths.append(f"{dim_name}：表现良好（{score}/{max_score}）")
        elif score <= max_score * 0.4:
            weaknesses.append(f"{dim_name}：需要加强（{score}/{max_score}）")

    # 漏问内容
    standard_fb = case_data.get("standard_feedback", {})
    must_mention = standard_fb.get("must_mention", [])
    for item in must_mention:
        missed.append(f"应关注: {item}")

    suggestions = standard_fb.get("summary", "请根据评分细节改进。")
    if severe_errors:
        suggestions = "严重错误: " + "; ".join(
            se.get("message", "") for se in severe_errors
        ) + " " + suggestions

    return {
        "strengths": strengths if strengths else ["本次训练无明显突出表现"],
        "weaknesses": weaknesses if weaknesses else ["各项表现均在合理范围"],
        "missed_content": missed,
        "suggestions": suggestions,
    }
