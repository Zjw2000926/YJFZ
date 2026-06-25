"""将旧格式动态病例转换为新 patient_states 格式

旧格式: dynamic_timeline.events[{minute, trigger, patient_expression, vital_changes}]
新格式: patient_states[{state_id, time_minute, appearance, chief_complaint, vital_signs, ...}]

用法: python tools/migrate_dynamic_cases.py [--dry-run]
"""
import json, os, sys, argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "triage_data")
TARGET_DIR = os.path.join(BASE, "cases_dynamic")

# 旧字段名 → 新字段名 映射
VITAL_KEY_MAP = {
    "temperature_c": "temperature", "temperature": "temperature",
    "heart_rate_bpm": "heart_rate", "heart_rate": "heart_rate",
    "respiratory_rate_bpm": "respiratory_rate", "respiratory_rate": "respiratory_rate",
    "systolic_bp_mmhg": "blood_pressure_systolic",
    "diastolic_bp_mmhg": "blood_pressure_diastolic",
    "blood_pressure_systolic": "blood_pressure_systolic",
    "blood_pressure_diastolic": "blood_pressure_diastolic",
    "spo2_percent": "spo2", "spo2": "spo2",
    "pain_score": "pain_score",
    "consciousness": "consciousness",
    "gcs_score": "gcs_score",
    "blood_glucose": "blood_glucose",
    "blood_glucose_mmol_l": "blood_glucose",
}


def _to_float(val):
    """安全转为 float，失败返回 None"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_bp(value):
    """解析血压字符串如 '104/66 mmHg' → (systolic, diastolic)"""
    if value is None:
        return None, None
    s = str(value).replace("mmHg", "").replace("mmhg", "").strip()
    parts = s.split("/")
    if len(parts) >= 2:
        return _to_float(parts[0].strip()), _to_float(parts[1].strip())
    return None, None


def map_vitals(old_vitals: dict) -> dict:
    """将旧字段名映射到新 patient_states.vital_signs 格式，统一数值类型"""
    new = {}
    for old_key, value in old_vitals.items():
        if old_key in ("description", "event_id", "patient_expression", "source_field"):
            continue
        new_key = VITAL_KEY_MAP.get(old_key, old_key)

        # 处理嵌套值
        if isinstance(value, dict):
            val = value.get("value", str(value))
        else:
            val = value

        # 跳过空值
        if val is None or val == "":
            continue

        new[new_key] = val

    # 解析复合血压字符串
    bp_str = new.pop("blood_pressure", None)
    if bp_str:
        sys_val, dia_val = _parse_bp(bp_str)
        if sys_val is not None:
            new["blood_pressure_systolic"] = sys_val
        if dia_val is not None:
            new["blood_pressure_diastolic"] = dia_val

    # 统一数值类型
    for key in list(new.keys()):
        val = new[key]
        num = _to_float(val)
        if num is not None:
            new[key] = int(num) if num == int(num) else num

    return new


def build_t0_state(case: dict) -> dict:
    """从病例初始数据构建 T0 患者状态"""
    pp = case.get("patient_profile", {})
    ie = case.get("initial_exposure", {})
    sa = case.get("standard_answer", {})

    # 从 required_measurements 提取 T0 体征并用 map_vitals 标准化
    raw_vitals = {}
    for m in case.get("required_measurements", []):
        vid = m.get("id", "")
        val = m.get("value", "")
        if val != "" and val is not None:
            raw_vitals[vid] = val
    vitals = map_vitals(raw_vitals)

    return {
        "state_id": "T0_initial",
        "state_name": pp.get("appearance", "")[:30] or "初始状态",
        "time_minute": 0,
        "appearance": pp.get("appearance", ""),
        "chief_complaint": ie.get("chief_complaint", ""),
        "symptom_description": ie.get("scene_description", ""),
        "mental_status": "清醒",
        "pain_score": vitals.get("pain_score", 0),
        "risk_signals": [cs.get("label", "") for cs in case.get("critical_signals", [])[:3]],
        "available_dialogue_slots": ["chief_complaint", "onset", "pain_location", "pain_nature", "accompanying", "past_history"],
        "vital_signs": vitals,
        "recommended_actions": [f"初始分诊{sa.get('triage_level', '')}", f"{sa.get('triage_zone', '')}候诊"],
        "standard_triage_level": sa.get("triage_level", ""),
        "standard_area": sa.get("triage_zone", ""),
    }


def build_event_state(case: dict, event: dict, index: int, t0_vitals: dict = None) -> dict:
    """从一个 timeline event 构建患者状态"""
    pp = case.get("patient_profile", {})
    minute = event.get("minute", event.get("scheduled_minute", 0))
    expr = event.get("patient_expression", "")[:40]
    vitals = map_vitals(event.get("vital_changes", {}))
    # 如果 event 只有 description 无数值，继承 T0 体征并做偏移
    if not vitals or all(v is None for v in vitals.values()):
        vitals = dict(t0_vitals) if t0_vitals else {}
        desc = event.get("patient_expression", "")
        if any(kw in desc for kw in ["加重", "恶化", "更差", "疼痛", "疼"]):
            vitals["pain_score"] = min(10, int(float(vitals.get("pain_score", 5) or 5)) + 2)
        if any(kw in desc for kw in ["心率", "脉搏", "快", "HR", "心动过"]):
            vitals["heart_rate"] = int(float(vitals.get("heart_rate", 80) or 80)) + 15
        if any(kw in desc for kw in ["血压", "低", "下降", "BP", "mmHg"]):
            bp_sys = int(float(vitals.get("blood_pressure_systolic", 120) or 120)) - 15
            bp_dia = int(float(vitals.get("blood_pressure_diastolic", 70) or 70)) - 8
            vitals["blood_pressure_systolic"] = bp_sys
            vitals["blood_pressure_diastolic"] = bp_dia
        if any(kw in desc for kw in ["呼吸", "气促", "喘"]):
            vitals["respiratory_rate"] = int(float(vitals.get("respiratory_rate", 18) or 18)) + 3
    # 推断严重程度
    is_deterioration = bool(event.get("requires_reassessment"))
    level = case.get("standard_answer", {}).get("triage_level", "Ⅲ级")
    if is_deterioration and minute >= 25:
        level = "Ⅱ级"  # T25+ 恶化通常需要升级
    area = case.get("standard_answer", {}).get("triage_zone", "黄区")
    if is_deterioration and minute >= 25:
        area = "红区"

    return {
        "state_id": f"T{minute}_event_{index}",
        "state_name": expr,
        "time_minute": minute,
        "appearance": pp.get("appearance", ""),
        "chief_complaint": expr,
        "symptom_description": event.get("patient_expression", "")[:80],
        "mental_status": "清醒" if not is_deterioration else "清醒但烦躁",
        "pain_score": vitals.get("pain_score", 5),
        "risk_signals": ["病情变化"] if is_deterioration else [],
        "available_dialogue_slots": ["current_symptoms", "pain_change", "new_symptoms"],
        "vital_signs": vitals,
        "recommended_actions": ["复评生命体征", "评估病情变化"] if not is_deterioration else ["升级分诊等级", "通知医生", "调整区域"],
        "standard_triage_level": level,
        "standard_area": area,
    }


def migrate_case(case: dict) -> dict:
    """转换单个病例到新格式"""
    dt = case.get("dynamic_timeline", {})
    if not dt.get("enabled"):
        return case

    events = dt.get("events", [])
    if not events:
        return case

    # 已有 patient_states 则跳过
    if len(case.get("patient_states", [])) >= 2:
        return case

    sa = case.get("standard_answer", {})

    # 构建 patient_states
    t0_state = build_t0_state(case)
    states = [t0_state]
    t0_vitals = t0_state.get("vital_signs", {})
    for i, ev in enumerate(events):
        states.append(build_event_state(case, ev, i + 1, t0_vitals))

    case["patient_states"] = states

    # 补全标准字段
    case["standard_initial_triage_level"] = sa.get("triage_level", "")
    case["standard_initial_area"] = sa.get("triage_zone", "")
    # 最终等级取最后一个 event 的推断等级
    case["standard_final_triage_level"] = states[-1].get("standard_triage_level", sa.get("triage_level", ""))
    case["standard_final_area"] = states[-1].get("standard_area", sa.get("triage_zone", ""))

    # 更新 event 格式: 增补缺失字段
    for ev in events:
        ev.setdefault("event_type", ev.get("trigger", "time_elapsed"))
        ev.setdefault("scheduled_minute", ev.get("minute", 0))
        ev.setdefault("event_description", ev.get("patient_expression", "")[:60])
        ev.setdefault("visible_to_student", ev.get("visible_to_trainee", True))
        ev.setdefault("student_prompt", "请关注患者病情变化" if ev.get("requires_reassessment") else "")
        ev.setdefault("requires_reassessment", ev.get("requires_reassessment", False))
        # 推断是否严重错误
        if ev.get("requires_reassessment") and ev.get("scheduled_minute", ev.get("minute", 0)) >= 25:
            ev.setdefault("severe_error_if_ignored", True)
            ev.setdefault("severe_error_code", "NO_REASSESS_AFTER_WORSENING")
        # 标准化 vital_changes
        ev["vital_changes"] = map_vitals(ev.get("vital_changes", {}))

    # 清理旧格式字段
    for ev in events:
        ev.pop("minute", None)
        ev.pop("trigger", None)
        ev.pop("visible_to_trainee", None)

    # 补全 dynamic_scoring_rubric（使用默认维度）
    if not case.get("dynamic_scoring_rubric"):
        case["dynamic_scoring_rubric"] = {
            "total_score": 100,
            "dimensions": [
                {"name": "初始第一眼评估", "max_score": 8, "key": "initial_first_look"},
                {"name": "初始病史采集", "max_score": 12, "key": "initial_history"},
                {"name": "初始生命体征评估", "max_score": 12, "key": "initial_vitals"},
                {"name": "初始高危信号识别", "max_score": 15, "key": "initial_risk_signals"},
                {"name": "初始分诊等级", "max_score": 15, "key": "initial_triage_level"},
                {"name": "初始处置安排", "max_score": 8, "key": "initial_disposition"},
                {"name": "复评时间设置", "max_score": 8, "key": "reassessment_timing"},
                {"name": "复评内容完成", "max_score": 10, "key": "reassessment_content"},
                {"name": "病情变化识别与升级", "max_score": 8, "key": "deterioration_response"},
                {"name": "沟通记录", "max_score": 4, "key": "communication"},
            ]
        }

    if not case.get("dynamic_severe_errors"):
        case["dynamic_severe_errors"] = [
            {"code": "NO_REASSESS_AFTER_WORSENING", "condition": "student_did_not_reassess",
             "message": "患者病情恶化后未进行复评", "critical_fail": True, "score_cap": 59},
            {"code": "NO_UPGRADE_AFTER_WORSENING", "condition": "reassessed_but_not_upgraded",
             "message": "复评后病情恶化仍未升级分诊等级", "critical_fail": True, "score_cap": 59},
        ]

    # 补全 required_dynamic_actions
    if not case.get("required_dynamic_actions"):
        case["required_dynamic_actions"] = [
            "first_look_observation", "history_taking", "vital_signs_measurement",
            "initial_triage_decision", "advance_time", "reassess", "submit_case"
        ]

    return case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not os.path.isdir(TARGET_DIR):
        print(f"目录不存在: {TARGET_DIR}")
        return

    converted = 0
    skipped = 0
    for fname in sorted(os.listdir(TARGET_DIR)):
        if not fname.endswith(".json"):
            continue
        # 跳过已有的新格式 MVP 病例
        if "DYN-RLQ" in fname:
            continue

        path = os.path.join(TARGET_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            case = json.load(f)

        if not case.get("is_dynamic"):
            skipped += 1
            continue

        old_states = len(case.get("patient_states", []))
        new_case = migrate_case(case)
        new_states = len(new_case.get("patient_states", []))

        if new_states > old_states:
            if not args.dry_run:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(new_case, f, ensure_ascii=False, indent=2)
            converted += 1
            print(f"{'[DRY-RUN]' if args.dry_run else 'Migrated'} {fname}: {old_states}→{new_states} states, events={len(new_case.get('dynamic_timeline', {}).get('events', []))}")
        else:
            skipped += 1

    print(f"\nConverted: {converted}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
