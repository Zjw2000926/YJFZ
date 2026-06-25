# 数据模型

## 病例结构 (52 cases)

```
triage_data/
├── cases/           17 静态病例 (含 TRIAGE-STATIC-CHEST-II-001)
└── cases_dynamic/   35 动态病例 (全部含 patient_states ≥3)
```

### 完整动态病例字段

```json
{
  "external_id": "TRIAGE-DYN-RLQ-001",
  "is_dynamic": true,
  "stage": "PUBLISHED",
  "review_status": {"approved_for_training": true},

  "patient_states": [{
    "state_id": "T0_initial", "time_minute": 0,
    "appearance": "...", "chief_complaint": "...",
    "vital_signs": {"heart_rate": 94, "blood_pressure_systolic": 118, ...},
    "standard_triage_level": "Ⅲ级", "standard_area": "黄区",
    "recommended_actions": [...]
  }],

  "dynamic_timeline": {
    "enabled": true,
    "events": [{
      "event_id": "EVT_T15_PAIN_WORSENING",
      "scheduled_minute": 15, "event_type": "symptom_worsening",
      "patient_state_id": "T15_event_1",
      "patient_expression": "疼得更厉害了...",
      "requires_reassessment": true,
      "vital_changes": {"heart_rate": 108, ...},
      "severe_error_if_ignored": true
    }]
  },

  "dynamic_scoring_rubric": {"total_score": 100, "dimensions": [...]},
  "dynamic_severe_errors": [{"code": "NO_REASSESS_AFTER_WORSENING", ...}],
  "standard_initial_triage_level": "Ⅲ级",
  "standard_final_triage_level": "Ⅱ级",
  "dynamic_feedback": {...}
}
```

### 患者变体 (3类)

每个病例含 ≥3 个 `patient_variants`: standard / colloquial / anxious_vague，配以 `emotional_state`、`proxy_mode`、`forbidden_disclosure`、`allowed_disclosure_by_stage`。

## 训练记录结构

```json
{
  "id": "abc123",
  "case_external_id": "TRIAGE-DYN-RLQ-001",
  "mode": "practice",
  "status": "scored",
  "messages": [...],
  "student_actions": [
    {"action_type": "measure_vitals", "simulation_minute": 0},
    {"action_type": "initial_triage", ...},
    {"action_type": "advance_time", ...},
    {"action_type": "reassess", ...},
    {"action_type": "upgrade_triage", ...},
    {"action_type": "notify_doctor", ...},
    {"action_type": "record_note", ...},
    {"action_type": "submit", ...}
  ],
  "triage_decisions": [
    {"decision_type": "initial", "level": "Ⅲ级", ...},
    {"decision_type": "reassessment", "level": "Ⅱ级", ...}
  ],
  "vital_measurement_log": [
    {"simulation_minute": 0, "result": {...}},
    {"simulation_minute": 15, "result": {...}},
    {"simulation_minute": 30, "result": {...}}
  ],
  "timeline_state": {
    "current_stage": "COMPLETED",
    "stage_history": [...],
    "current_simulated_minute": 30,
    "reassessment_completed": true,
    "reassessment_on_time": true
  },
  "timeline_report": {
    "standard_initial_level": "Ⅲ级", "student_initial_level": "Ⅲ级",
    "standard_final_level": "Ⅱ级", "student_final_level": "Ⅱ级",
    "reassessment_on_time": true, "deterioration_recognized": true,
    "triage_upgraded": true, "doctor_notified": true
  }
}
```

## 状态机 (13 states)

```
NOT_STARTED → ARRIVAL → FIRST_LOOK → HISTORY_TAKING
→ INITIAL_VITALS → INITIAL_TRIAGE → WAITING
→ REASSESSMENT_DUE / DETERIORATED → REASSESSMENT
→ RE_TRIAGE → FINAL_DISPOSITION → COMPLETED
```

所有状态可以从任何阶段直接 submit → COMPLETED。

## 规则引擎

- `vital_thresholds_v1.json`: 20 条 (SpO₂/BP/HR/RR/Temp/Pain/GCS/Glucose/SI/MEWS)
- `triage_rule_set_v1.json`: 23 条 (心脏胸痛/卒中/呼吸衰竭/过敏/脓毒症/异位妊娠/PE/大创伤/脱水/心律失常/自杀/SAH/大出血/中毒/产科急症/儿童惊厥/暴力/感染暴露/急腹症 + 特殊人群升级)

## 评测数据

- `triage_eval_intents.jsonl`: 20 条意图识别评测
- `triage_eval_scoring.jsonl`: 5 条评分评测
