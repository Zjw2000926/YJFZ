"""V6 完整平台服务：多患者场景 + 个性化学习路径 + 科研导出 + 安全审计 + AI事件日志"""

import json, os, uuid, hashlib
from datetime import datetime, timezone

from config import TRIAGE_RUNTIME_DATA_DIR

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 运行时数据（学习路径/AI事件/安全审计等 — 必须可写）
DATA = TRIAGE_RUNTIME_DATA_DIR

def _load(fpath):
    if not os.path.exists(fpath): return []
    with open(fpath, encoding="utf-8") as f: return json.load(f)
def _save(fpath, data):
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    tmp = fpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fpath)  # 原子替换，防止并发损坏

# ── Multi-Patient Scenarios ──
SCENARIOS_FILE = os.path.join(DATA, "scenarios", "scenarios.json")
SCENARIO_PATIENTS_FILE = os.path.join(DATA, "scenarios", "scenario_patients.json")
QUEUE_RECORDS_FILE = os.path.join(DATA, "scenarios", "queue_records.json")

def list_scenarios():
    return _load(SCENARIOS_FILE)

def get_scenario(sid):
    return next((s for s in _load(SCENARIOS_FILE) if s["id"] == sid), None)

def create_scenario(external_id, title, scenario_type, difficulty, description, resource_context=None, standard_strategy=None):
    scenarios = _load(SCENARIOS_FILE)
    s = {"id": str(uuid.uuid4())[:8], "external_id": external_id, "title": title,
         "scenario_type": scenario_type, "difficulty": difficulty, "description": description,
         "resource_context": resource_context or {}, "standard_strategy": standard_strategy or {},
         "expert_review_status": "pending", "created_at": datetime.now(timezone.utc).isoformat()}
    scenarios.append(s); _save(SCENARIOS_FILE, scenarios); return s

def add_scenario_patient(scenario_id, patient_external_id, case_external_id, arrival_minute=0, priority_order=0, scenario_role="patient"):
    patients = _load(SCENARIO_PATIENTS_FILE)
    p = {"id": str(uuid.uuid4())[:8], "scenario_id": scenario_id, "patient_external_id": patient_external_id,
         "case_external_id": case_external_id, "arrival_minute": arrival_minute,
         "initial_visibility": "visible", "priority_order": priority_order, "scenario_role": scenario_role}
    patients.append(p); _save(SCENARIO_PATIENTS_FILE, patients); return p

def start_queue_record(record_id, scenario_id):
    records = _load(QUEUE_RECORDS_FILE)
    qr = {"id": str(uuid.uuid4())[:8], "record_id": record_id, "scenario_id": scenario_id,
          "queue_state": {}, "selected_priority_order": [], "resource_allocation": {},
          "final_queue_score": None, "created_at": datetime.now(timezone.utc).isoformat()}
    records.append(qr); _save(QUEUE_RECORDS_FILE, records); return qr

def save_queue_result(record_id, priority_order, resource_allocation, final_score):
    records = _load(QUEUE_RECORDS_FILE)
    for qr in records:
        if qr["record_id"] == record_id:
            qr["selected_priority_order"] = priority_order
            qr["resource_allocation"] = resource_allocation
            qr["final_queue_score"] = final_score
            _save(QUEUE_RECORDS_FILE, records); return qr
    return None

# ── Learning Paths ──
LEARNING_PATHS_FILE = os.path.join(DATA, "learning_paths.json")

def generate_learning_path(user_id, profile_snapshot):
    paths = _load(LEARNING_PATHS_FILE)
    # Remove old active paths
    paths = [p for p in paths if not (p["user_id"] == user_id and p["status"] == "active")]
    recommendations = []
    snapshot = profile_snapshot.get("summary", {})
    if snapshot.get("under_triage_rate", 0) > 0.15:
        recommendations.append({"type": "category", "target": "critical_cases", "reason": "低估分诊率偏高，推荐Ⅰ/Ⅱ级高危病例训练", "priority": 1})
    if snapshot.get("triage_accuracy", 1) < 0.7:
        recommendations.append({"type": "category", "target": "neuro_cases", "reason": "分诊准确率偏低，推荐神经系统病例训练", "priority": 2})
    if snapshot.get("critical_recognition_rate", 1) < 0.7:
        recommendations.append({"type": "rule", "target": "vital_signs", "reason": "危重症识别率不足，推荐加强生命体征评估训练", "priority": 1})
    recs = [{"id": str(uuid.uuid4())[:8], "type": r["type"], "target": r["target"], "reason": r["reason"], "priority": r["priority"], "completed": False} for r in recommendations]
    path = {"id": str(uuid.uuid4())[:8], "user_id": user_id, "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile_snapshot": profile_snapshot, "recommendations": recs, "status": "active"}
    paths.append(path); _save(LEARNING_PATHS_FILE, paths)
    return path

def get_learning_path(user_id):
    paths = _load(LEARNING_PATHS_FILE)
    active = [p for p in paths if p["user_id"] == user_id and p["status"] == "active"]
    return active[0] if active else None

# ── Research Export ──
def export_research_data(deidentify=True):
    from services.triage_repository import RECORDS_DIR
    records = []
    if os.path.isdir(RECORDS_DIR):
        for fn in os.listdir(RECORDS_DIR):
            if fn.endswith(".json"):
                with open(os.path.join(RECORDS_DIR, fn), encoding="utf-8") as f:
                    records.append(json.load(f))
    result = []
    for r in records:
        row = {"case_category": r.get("case_external_id", "")[:20],
               "standard_level": r.get("score_detail", {}).get("standard_answer", {}).get("triage_level", ""),
               "student_level": r.get("final_level_selected", ""),
               "total_score": r.get("total_score"),
               "pass_status": r.get("pass_status"),
               "severe_error": r.get("severe_error_triggered", False),
               "disclosed_count": len(r.get("disclosed_slots", [])),
               "measured_count": len(r.get("measured_vitals", [])),
               "reassessment_count": len(r.get("timeline_state", {}).get("reassessments", [])),
               "teacher_review_score": r.get("teacher_review", {}).get("teacher_score_20"),
               }
        if deidentify:
            row["user_anon_id"] = hashlib.sha256(str(r.get("user_id", "")).encode()).hexdigest()[:12]
            row.pop("user_id", None)
            row.pop("user_display_name", None)
        else:
            row["user_id"] = r.get("user_id")
        result.append(row)
    return result

# ── Safety Audit ──
SAFETY_AUDITS_FILE = os.path.join(DATA, "safety_audits.json")
def log_safety_audit(audit_type, target_id, result, findings=None):
    audits = _load(SAFETY_AUDITS_FILE)
    a = {"id": str(uuid.uuid4())[:8], "audit_type": audit_type, "target_id": target_id, "result": result,
         "findings": findings or {}, "created_at": datetime.now(timezone.utc).isoformat()}
    audits.append(a); _save(SAFETY_AUDITS_FILE, audits); return a

def list_safety_audits():
    return _load(SAFETY_AUDITS_FILE)

# ── AI Events ──
AI_EVENTS_FILE = os.path.join(DATA, "ai_events.json")
def log_ai_event(record_id, purpose, model, prompt_version, input_summary, output, guard_result=None):
    events = _load(AI_EVENTS_FILE)
    e = {"id": str(uuid.uuid4())[:8], "record_id": record_id, "purpose": purpose, "model": model or "deepseek-chat",
         "prompt_version": prompt_version, "input_summary": input_summary[:200], "output": output[:500],
         "guard_result": guard_result or {}, "created_at": datetime.now(timezone.utc).isoformat()}
    events.append(e); _save(AI_EVENTS_FILE, events); return e

def list_ai_events(record_id=None):
    events = _load(AI_EVENTS_FILE)
    if record_id: return [e for e in events if e["record_id"] == record_id]
    return events

# ── Mural Cues expansion ──
# ── Voice Events ──
VOICE_EVENTS_FILE = os.path.join(DATA, "voice_events.json")
def log_voice_event(record_id, transcript, confidence=None, corrected_transcript=None):
    events = _load(VOICE_EVENTS_FILE)
    e = {"id": str(uuid.uuid4())[:8], "record_id": record_id, "transcript": transcript,
         "confidence": confidence, "corrected_transcript": corrected_transcript,
         "created_at": datetime.now(timezone.utc).isoformat()}
    events.append(e); _save(VOICE_EVENTS_FILE, events); return e

# ── Organizations ──
ORGS_FILE = os.path.join(DATA, "organizations.json")
SCOPES_FILE = os.path.join(DATA, "case_library_scopes.json")
def list_orgs(): return _load(ORGS_FILE)
def create_org(name, org_type): orgs=_load(ORGS_FILE); o={"id":str(uuid.uuid4())[:8],"name":name,"type":org_type,"created_at":datetime.now(timezone.utc).isoformat()}; orgs.append(o); _save(ORGS_FILE,orgs); return o
def set_case_scope(case_id, org_id, visibility="global"): scopes=_load(SCOPES_FILE); s={"id":str(uuid.uuid4())[:8],"case_id":case_id,"organization_id":org_id,"visibility":visibility,"created_at":datetime.now(timezone.utc).isoformat()}; scopes.append(s); _save(SCOPES_FILE,scopes); return s

# ── Calibration ──
def get_calibration_data():
    from services.triage_repository import RECORDS_DIR
    records = []
    if os.path.isdir(RECORDS_DIR):
        for fn in os.listdir(RECORDS_DIR):
            if fn.endswith(".json"):
                with open(os.path.join(RECORDS_DIR, fn), encoding="utf-8") as f: records.append(json.load(f))
    calibrated = []
    for r in records:
        tr = r.get("teacher_review")
        if tr:
            calibrated.append({"record_id": r["id"], "system_score": r.get("total_score",0),
                              "teacher_score": tr.get("teacher_score_20",0),
                              "final_score": tr.get("final_score",0),
                              "diff": abs(r.get("total_score",0)*0.8 - tr.get("teacher_score_20",0)),
                              "case_id": r.get("case_external_id","")})
    drift = round(sum(c["diff"] for c in calibrated) / max(len(calibrated), 1), 2) if calibrated else 0
    return {"records": calibrated, "count": len(calibrated), "avg_score_drift": drift, "target_agreement": 0.9}

# ── Mural Cues ──
def add_multimodal_cues(external_id, cues):
    """Add multimodal visual/behavioral cues to a case"""
    from services.triage_repository import get_case
    case = get_case(external_id)
    if case:
        case["multimodal_cues"] = cues
        return case
    return None
