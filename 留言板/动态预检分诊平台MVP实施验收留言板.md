# 动态预检分诊平台 MVP 实施验收留言板

创建日期：2026-06-19

目标：在不破坏现有静态预检分诊训练功能的基础上，把当前系统补齐为“基于病例时间轴和患者状态机的预检分诊动态训练平台”MVP，并明确后续编码步骤、文件范围、最终验收方法和达标检验方式。

重要边界：本文件记录后续需要完成的实施方法和验收方案，不代表本次已经完成全部功能编码。后续开发必须以当前系统已有结构为基础，不能照搬一套新架构。

## 一、当前系统基础

### 1. 技术栈

当前项目已经具备完整前后端结构：

1. 后端：FastAPI，主要入口为 `backend/main.py`，预检分诊路由集中在 `backend/routers/triage.py`。

2. 数据：SQLite + JSON 文件。病例、规则、评分标准主要在 `backend/triage_data/` 下；运行时记录主要写入 `backend/triage_data/records/` 或运行时数据目录。

3. 前端：React 19 + Vite 8 + React Router 7，预检分诊页面集中在 `frontend/src/pages/triage/`。

4. AI：已有 DeepSeek API 配置与受控患者对话服务，但分诊等级和严重错误不能交给 LLM 自由判断。

5. 现有训练模式：已有 `mode` 字段，支持 practice、exam、osce 等模式语义。后续不必新建独立 `trainingMode` 字段，可优先沿用 `mode`，必要时在前端内部映射为 `trainingMode`。

### 2. 当前已存在的动态能力

当前系统不是纯静态系统，已经有 V4 动态训练雏形：

1. `backend/services/triage_timeline.py`：已有时间轴初始化、模拟时间推进、事件触发、患者表现和生命体征变化应用。

2. `backend/services/triage_reassessment.py`：已有复评记录、复评完整性、是否需要升级、规则引擎复算。

3. `backend/services/triage_scoring_v4.py`：已有 100 分动态病例评分结构、复评维度、严重错误、一票否决和时间线报告初稿。

4. `backend/routers/triage.py`：已有 `/timeline`、`/timeline/advance`、`/reassess`、`/current-state`、`/upgrade` 等动态训练接口。

5. `frontend/src/pages/triage/TriageDynamicTraining.jsx`：已有动态训练页，支持问诊、测量生命体征、推进时间、复评、选择分诊等级和区域、提交。

6. `frontend/src/components/triage/TriageTimelinePanel.jsx`：已有前端时间线面板。

7. `frontend/src/pages/triage/TriageCaseSelect.jsx`：已有动态病例入口，`is_dynamic` 病例会进入 `/triage/dynamic/start?case=...`。

8. `frontend/src/pages/triage/TriageRecordDetail.jsx`：已有评分报告页面，可展示总分、分项评分、严重错误、专家反馈和部分时间线报告。

### 3. 当前病例数据现状

1. 静态病例目录：`backend/triage_data/cases/`。

2. 动态病例目录：`backend/triage_data/cases_dynamic/`。

3. 当前动态病例使用的字段是 `is_dynamic` 和 `dynamic_timeline`，并非用户文本中完整的 `Case / PatientState / TimelineEvent / VitalSignSet` 命名体系。后续应做兼容扩展，不要强行迁移所有现有病例。

4. 当前已有右下腹痛动态病例 `TRIAGE-019`，但它是“右下腹痛伴近晕厥、月经延迟待确认”，初始标准等级为Ⅱ级，时间节点约为 T5/T10，和用户要求的“初始Ⅲ级、T0/T15/T30、T30 升级Ⅱ级”不完全一致。

5. 当前已有静态胸痛病例 `TRIAGE-001`，但其专家标准是Ⅰ级红区，和用户文本中“胸痛静态病例标准Ⅱ级”不一致。后续验收静态兼容时应尊重现有专家病例标准；如果确实需要Ⅱ级胸痛样例，应新增病例，不要覆盖现有专家审核病例。

## 二、对用户要求的适配原则

1. 保留静态训练闭环。`TriageTraining.jsx`、静态病例数据、原有问诊、测量、提交评分逻辑不能被动态 MVP 改坏。

2. 动态能力只扩展当前 V4 模块。优先改 `triage_timeline.py`、`triage_reassessment.py`、`triage_scoring_v4.py`、`TriageDynamicTraining.jsx`，不要重写整套训练系统。

3. 病例数据继续 JSON 驱动。动态病例新增字段应放入 `cases_dynamic/*.json`，页面和后端根据数据渲染，不把 T0/T15/T30 写死到组件里。

4. 状态机要独立成模块。当前 `triage_timeline.py` 更像时间轴事件引擎，还不是完整患者状态机；应新增 `backend/services/triage_state_machine.py` 或在时间轴模块中拆分出明确状态机类。

5. 分诊等级、升级等级、严重错误和评分依据必须由病例标准答案、动态时间轴和规则引擎决定。LLM 只能负责病例内自然表达，不能决定最终等级。

6. 训练模式和考核模式沿用当前 `mode`。practice 显示提示和即时反馈；exam/osce 隐藏关键提示，提交后或教师发布后才显示详细反馈。

7. 系统仅用于教学训练。所有页面、报告、AI 提示词和导出结果都应保留“不可用于真实临床分诊”的安全边界。

## 三、建议新增或修改的文件清单

### 后端建议修改

1. `backend/services/triage_timeline.py`

   扩展为完整时间轴引擎，支持绝对时间节点、事件类型、训练/考核可见性、复评到期判断、事件后果、当前 PatientState。

2. `backend/services/triage_state_machine.py`

   建议新增。定义 NOT_STARTED、ARRIVAL、FIRST_LOOK、HISTORY_TAKING、INITIAL_VITALS、INITIAL_TRIAGE、WAITING、REASSESSMENT_DUE、DETERIORATED、REASSESSMENT、RE_TRIAGE、FINAL_DISPOSITION、COMPLETED 等状态，以及状态转移规则。

3. `backend/services/triage_reassessment.py`

   补齐复评时间设置、是否按时复评、复评后是否升级、是否通知医生、复评记录和重新分诊记录。

4. `backend/services/triage_scoring_v4.py`

   将用户给出的动态病例 100 分评分结构落到代码中，按学员操作时间线和复评结果评分，并实现严重错误一票否决。

5. `backend/services/triage_patient_v1.py`

   生命体征测量应优先读取当前时间节点/患者状态的生命体征，而不是只返回初始静态体征。

6. `backend/services/triage_repository.py`

   训练记录中补充 `student_actions`、`triage_decisions`、`vital_measurement_log`、`timeline_report` 等结构化字段。

7. `backend/routers/triage.py`

   在现有动态接口基础上补齐：设置复评时间、记录初始分诊、记录复评分诊、通知医生、记录说明、提交动态病例报告。已有接口尽量扩展 payload，不要重复造相似路由。

8. `backend/triage_data/cases_dynamic/TRIAGE-DYN-RLQ-001.json`

   建议新增一个专用 MVP 验收病例：右下腹痛候诊期间病情恶化。不要覆盖当前 `TRIAGE-019`。

9. `backend/tests/test_triage_dynamic_mvp.py`

   建议新增，覆盖动态病例从 T0 到 T30 的完整成功路径和严重错误路径。

10. `backend/tests/test_triage_static_compatibility.py`

   建议新增或扩展现有路由测试，证明静态胸痛病例仍能完成训练、测量、提交、评分和反馈。

### 前端建议修改

1. `frontend/src/pages/triage/TriageDynamicTraining.jsx`

   在现有动态页上补齐患者信息区、当前状态、初始分诊、复评时间设置、主动复评、重新分诊、通知医生、记录说明、训练/考核模式差异。

2. `frontend/src/components/triage/TriageTimelinePanel.jsx`

   增强为可展示 T0/T15/T30、当前模拟时间、已发生事件、隐藏/显示提示、需要复评提示的时间轴组件。

3. `frontend/src/pages/triage/TriageRecordDetail.jsx`

   补齐训练报告：病例基本信息、标准/学员初始分诊、标准/学员最终分诊、患者状态时间线、学员操作时间线、生命体征测量记录、复评是否按时、是否升级、是否通知医生、严重错误和后续建议。

4. `frontend/src/api.js`

   增加或整理动态训练 API：设置复评时间、记录初始决策、记录复评决策、通知医生、保存说明、获取完整动态报告。

5. `frontend/src/__tests__/TriageDynamicTraining.test.jsx`

   建议新增，覆盖动态页面能选择测量项、推进时间、复评、升级分诊和提交。

6. `frontend/src/styles/triage.css`

   如需统一样式，将动态训练页内联样式逐步迁移到 CSS，避免页面组件过长。

## 四、数据结构落地方案

用户给出的数据结构语义是正确的，但需要映射到当前 JSON 病例体系中。

### 1. Case 映射

当前已有：

1. `external_id` 对应 `case_id`。

2. `display_name` / `title` 对应 `case_name`。

3. `is_dynamic` 和 `dynamic_timeline.enabled` 对应 `case_type` 与 `is_dynamic_case`。

4. `patient_profile`、`initial_exposure`、`standard_answer`、`required_questions`、`required_measurements`、`severe_errors`、`scoring_rubric`、`feedback` 已存在。

需要补齐：

1. `standard_initial_triage_level`

2. `standard_final_triage_level`

3. `standard_initial_area`

4. `standard_final_area`

5. `patient_states`

6. `required_dynamic_actions`

7. `dynamic_scoring_rubric`

8. `dynamic_feedback`

建议做法：新增字段时保留旧字段，同时在读取病例时做兼容解析。这样旧病例不会被破坏。

### 2. PatientState 落地

建议在动态病例中新增：

```json
"patient_states": [
  {
    "state_id": "T0_initial",
    "state_name": "初始右下腹痛",
    "time_minute": 0,
    "appearance": "右手捂右下腹，表情痛苦但能交流",
    "chief_complaint": "右下腹痛6小时，逐渐加重",
    "symptom_description": "轻度恶心，无呕吐，无腹泻",
    "mental_status": "清醒",
    "pain_score": 5,
    "risk_signals": ["育龄女性腹痛", "疼痛逐渐加重"],
    "available_dialogue_slots": ["chief_complaint", "onset", "pregnancy_possibility"],
    "vital_signs": {
      "temperature": 37.8,
      "heart_rate": 94,
      "respiratory_rate": 20,
      "blood_pressure_systolic": 118,
      "blood_pressure_diastolic": 74,
      "spo2": 98,
      "pain_score": 5,
      "consciousness": "清楚"
    },
    "recommended_actions": ["初始分诊Ⅲ级", "黄区候诊", "30分钟内复评"],
    "standard_triage_level": "Ⅲ级",
    "standard_area": "黄区"
  }
]
```

T15、T30 各新增一个 PatientState。T30 标准等级应为Ⅱ级，区域为红区或急诊优先处置区。

### 3. TimelineEvent 落地

建议继续使用当前 `dynamic_timeline.events`，但补齐字段：

1. `event_type`

2. `trigger_condition`

3. `patient_state_id`

4. `event_description`

5. `visible_to_student`

6. `student_prompt`

7. `requires_reassessment`

8. `expected_student_actions`

9. `consequence_if_missed`

10. `standard_level_after_event`

11. `severe_error_if_ignored`

### 4. VitalSignSet 落地

当前系统生命体征字段命名不完全统一，例如有 `heart_rate_bpm`、`spo2_percent`、`systolic_bp_mmhg` 等。后续不要一次性重命名全部旧数据，建议新增一个标准化函数：

1. 输入：病例原始生命体征、当前 PatientState、当前 timeline event 的 `vital_changes`。

2. 输出：统一的 `VitalSignSet`，同时保留前端展示需要的 `display_value`。

3. 测量记录：写入 `record.vital_measurement_log`，每条包含 `simulation_minute`、`state_id`、`measurement_ids`、`result`。

### 5. StudentAction 与 TriageDecision 落地

当前训练记录已有 messages、measured_vitals、final_level_selected 等字段，但不够表达动态流程。建议新增：

1. `record.student_actions`

2. `record.triage_decisions`

3. `record.notification_events`

4. `record.notes`

每次问诊、测量、观察、初始分诊、设置复评时间、推进时间、复评、重新分诊、通知医生、记录说明、提交，都写入 `student_actions`。初始分诊和复评分诊分别写入 `triage_decisions`，不能只覆盖 `final_level_selected`。

## 五、MVP 编码实施步骤

### 阶段 0：基线保护

1. 运行现有测试，记录基线：

```powershell
cd backend
pytest -q
```

```powershell
cd frontend
npm.cmd run lint
npm.cmd run test -- --run
npm.cmd run build
```

2. 确认静态病例入口仍为 `/triage/training/start?case=...`，动态病例入口仍为 `/triage/dynamic/start?case=...`。

3. 不删除 `TriageTraining.jsx` 中原有静态训练能力。

### 阶段 1：新增 MVP 动态腹痛病例

新增 `backend/triage_data/cases_dynamic/TRIAGE-DYN-RLQ-001.json`。

病例必须满足：

1. 患者：女，34岁，自行步入急诊。

2. T0：右下腹痛 6 小时，T 37.8℃，HR 94，R 20，BP 118/74，SpO2 98%，NRS 5，标准Ⅲ级，黄区，30分钟内复评。

3. T15：疼痛和恶心加重，HR 108，BP 108/68，R 22，T 38.0℃，NRS 7，需要提前复评和通知医生关注。

4. T30：面色苍白、冷汗、头晕，T 38.3℃，HR 122，R 24，BP 96/60，SpO2 97%，NRS 8，标准升级Ⅱ级，红区或急诊优先处置区，立即通知医生。

5. 严重错误：恶化后未复评、复评后未升级、继续Ⅲ/Ⅳ级候诊、未通知医生。

6. 病例必须带 `review_status` 草稿或待专家审核标识；正式用于考试前必须专家审核。

### 阶段 2：补齐患者状态机

新增或扩展状态机模块，至少包含：

1. NOT_STARTED

2. ARRIVAL

3. FIRST_LOOK

4. HISTORY_TAKING

5. INITIAL_VITALS

6. INITIAL_TRIAGE

7. WAITING

8. REASSESSMENT_DUE

9. DETERIORATED

10. REASSESSMENT

11. RE_TRIAGE

12. FINAL_DISPOSITION

13. COMPLETED

状态推进规则：

1. 启动动态训练后进入 ARRIVAL。

2. 记录第一眼观察后进入 FIRST_LOOK。

3. 问诊后进入 HISTORY_TAKING。

4. 测量初始生命体征后进入 INITIAL_VITALS。

5. 提交初始分诊后进入 INITIAL_TRIAGE，再进入 WAITING。

6. 模拟时间到达复评点进入 REASSESSMENT_DUE。

7. 时间轴触发恶化事件进入 DETERIORATED。

8. 学员主动复评进入 REASSESSMENT。

9. 学员重新选择分诊等级进入 RE_TRIAGE。

10. 通知医生、调整区域、记录说明后进入 FINAL_DISPOSITION。

11. 提交病例后进入 COMPLETED。

验收要点：状态不能只显示在页面上，必须记录在 `record.timeline_state.current_stage` 或等价字段中。

### 阶段 3：扩展时间轴引擎

在 `triage_timeline.py` 中补齐：

1. 按绝对分钟推进到 T15、T30，而不是只按相对分钟累加。

2. 从 `patient_states` 读取当前患者外观、主诉、回答内容和生命体征。

3. practice 模式下返回 `student_prompt` 和复评提醒。

4. exam/osce 模式下隐藏关键提示，只返回患者自然表现变化。

5. 到达复评时间时记录是否逾期。

6. 触发恶化事件后设置 `requires_reassessment=true`。

7. 写入系统事件到 `record.student_actions` 或 `record.timeline_state.system_events`。

### 阶段 4：动态生命体征

测量接口必须根据当前模拟时间返回不同结果：

1. T0 测量返回 T0 PatientState 的生命体征。

2. T15 测量返回 T15 PatientState 的生命体征。

3. T30 测量返回 T30 PatientState 的生命体征。

4. 生命体征展示可以标记异常，但不能直接提示“应升级Ⅱ级”。

5. 每次测量必须记录 `simulation_minute`、测量项目、返回结果。

6. 若 T30 后未重新测量 BP、HR、疼痛评分等关键项目，评分时扣分。

### 阶段 5：初始分诊与复评分诊分离

当前系统主要用 `final_level_selected` 存最终分诊。动态 MVP 需要明确两次决策：

1. 初始分诊：`decision_type=initial`，保存学员 T0 选择的等级、区域、复评时间、理由。

2. 复评分诊：`decision_type=reassessment`，保存学员 T15/T30 后选择的等级、区域、是否通知医生、是否启动通道、理由。

3. 最终提交时 `final_level_selected` 可以保留，但应由最后一次 `triage_decisions` 同步而来。

4. 报告必须能同时展示“标准初始等级/学员初始等级”和“标准最终等级/学员最终等级”。

### 阶段 6：动态评分与严重错误

按用户给出的 V4 100 分结构落地：

1. 初始第一眼评估：8分。

2. 初始病史采集：12分。

3. 初始生命体征评估：12分。

4. 初始高危信号识别：15分。

5. 初始分诊等级：15分。

6. 初始处置安排：8分。

7. 复评时间设置：8分。

8. 复评内容完成：10分。

9. 病情变化识别与升级：8分。

10. 沟通记录：4分。

严重错误一票否决必须覆盖：

1. 患者恶化后未复评。

2. 复评后生命体征恶化仍未升级。

3. 候诊区危重化未通知医生。

4. 未记录病情变化和重新分诊结果。

5. 将Ⅱ级高危患者判为Ⅳ级。

6. 静态胸痛伴冷汗、放射痛、心血管危险因素时未识别心源性胸痛风险。

7. 系统不得给出真实临床治疗建议。

### 阶段 7：前端动态训练页

在 `TriageDynamicTraining.jsx` 中补齐以下区域：

1. 患者信息区：姓名或编号、年龄、性别、来院方式、当前主诉、当前外观、当前状态。

2. 病例时间轴区：T0、T15、T30、当前模拟时间、已发生事件；exam/osce 模式隐藏关键提示。

3. 操作区：问诊、第一眼观察、测量生命体征、初始分诊、设置复评时间、继续候诊、主动复评、重新测量、升级分诊、通知医生、记录说明、提交。

4. 动态生命体征区：按当前患者状态返回测量结果，显示异常标记但不替学员给答案。

5. 评分反馈入口：提交后跳转报告页，practice 可立即显示详细反馈，exam/osce 按任务配置隐藏。

### 阶段 8：训练报告

在 `TriageRecordDetail.jsx` 和后端评分结果中补齐训练报告：

1. 病例基本信息。

2. 标准初始分诊等级与学员初始分诊等级。

3. 标准最终分诊等级与学员最终分诊等级。

4. 患者状态时间线。

5. 学员操作时间线。

6. 生命体征测量记录。

7. 是否按时复评。

8. 是否识别病情恶化。

9. 是否升级分诊。

10. 是否通知医生。

11. 是否触发严重错误。

12. 总分和分项得分。

13. 正确点。

14. 错误点。

15. 标准分诊依据。

16. 后续训练建议。

### 阶段 9：模式差异

practice 模式：

1. 可显示患者状态变化提示。

2. 可提醒复评。

3. 提交后显示完整反馈。

exam/osce 模式：

1. 不主动显示“需要复评”“应升级”等关键提示。

2. 可以显示患者自然表现变化，例如“面色苍白、出冷汗”。

3. 限制完成时间。

4. 提交后是否显示反馈由任务配置决定。

## 六、最终验收标准

### 1. 静态兼容验收

验收目标：新增动态能力不影响原有静态训练。

必须通过：

1. 静态病例列表能正常加载。

2. 至少一个静态胸痛病例能进入训练页。

3. 学员能问诊、测量生命体征、选择分诊等级、选择区域、提交。

4. 系统能生成评分和反馈。

5. 静态病例不强制显示动态时间轴、复评按钮或 T0/T15/T30 流程。

建议检验方法：

1. 后端自动测试：新增或扩展 `test_triage_static_compatibility.py`，用 TestClient 完成 start -> message -> measure -> submit。

2. 前端测试：确认 `TriageTraining.jsx` 原有页面仍可渲染，静态病例点击仍跳转 `/triage/training/start?case=...`。

3. 手工验收：用学生账号打开一个静态胸痛病例，完整提交一次并查看报告。

### 2. 动态病例数据验收

验收目标：至少一个动态病例完整满足 T0/T15/T30。

必须通过：

1. `TRIAGE-DYN-RLQ-001.json` 存在于 `backend/triage_data/cases_dynamic/`。

2. `is_dynamic=true`。

3. `dynamic_timeline.enabled=true`。

4. 至少有 T0、T15、T30 三个患者状态。

5. T0 标准等级为Ⅲ级，标准区域为黄区。

6. T30 标准等级为Ⅱ级，标准区域为红区或急诊优先处置区。

7. 每个时间节点都有生命体征集合。

8. 严重错误清单包含恶化后未复评、复评后未升级、未通知医生。

建议检验方法：

```powershell
@'
import json
from pathlib import Path
p = Path("backend/triage_data/cases_dynamic/TRIAGE-DYN-RLQ-001.json")
data = json.loads(p.read_text(encoding="utf-8"))
assert data["is_dynamic"] is True
assert data["dynamic_timeline"]["enabled"] is True
states = data.get("patient_states", [])
minutes = {s["time_minute"] for s in states}
assert {0, 15, 30}.issubset(minutes)
assert any(s["time_minute"] == 0 and s["standard_triage_level"] == "Ⅲ级" for s in states)
assert any(s["time_minute"] == 30 and s["standard_triage_level"] == "Ⅱ级" for s in states)
print("dynamic case schema ok")
'@ | python -
```

### 3. 状态机验收

验收目标：动态病例不是静态展示，而是由状态机和时间轴驱动。

必须通过：

1. 启动病例后状态为 ARRIVAL 或 FIRST_LOOK。

2. 完成初始问诊、初始测量、初始分诊后进入 WAITING。

3. 推进到 T15 后出现状态变化，允许提前复评。

4. 推进到 T30 后进入 DETERIORATED 或 REASSESSMENT_DUE。

5. 完成复评和重新分诊后进入 RE_TRIAGE 或 FINAL_DISPOSITION。

6. 提交后进入 COMPLETED。

建议检验方法：

1. 后端单元测试直接调用状态机模块，断言每个 action 后的状态。

2. API 测试调用 `/timeline/advance`、`/reassess`、`/upgrade`，断言 `timeline_state.current_stage`。

### 4. 动态生命体征验收

验收目标：同一病例不同时间点测量结果不同。

必须通过：

1. T0 测量 HR 为 94，BP 为 118/74，NRS 为 5。

2. T15 测量 HR 为 108，BP 为 108/68，NRS 为 7。

3. T30 测量 HR 为 122，BP 为 96/60，NRS 为 8。

4. 每次测量都记录 simulation_minute 和 measurement_ids。

5. T30 后如果未重新测量 BP、HR、疼痛评分，应扣分。

建议检验方法：

1. 后端测试：推进时间后调用测量接口，断言返回值变化。

2. 报告测试：提交后断言 `vital_measurement_log` 中包含 T0/T15/T30 记录。

### 5. 初始分诊与复评分诊验收

验收目标：系统能记录两次分诊决策。

必须通过：

1. 初始分诊保存为 `decision_type=initial`。

2. 复评分诊保存为 `decision_type=reassessment`。

3. 初始标准Ⅲ级和学员初始选择可在报告中对比。

4. 最终标准Ⅱ级和学员最终选择可在报告中对比。

5. 如果 T30 后仍选择Ⅲ级或Ⅳ级，应判定未升级。

建议检验方法：

1. 后端测试提交一次初始决策和一次复评决策，断言 `triage_decisions` 长度至少为 2。

2. 前端报告页测试断言“初始分诊”和“复评分诊/最终分诊”两个区块均显示。

### 6. 严重错误验收

验收目标：关键安全错误必须一票否决。

必须通过以下负向用例：

1. 推进到 T30 后直接提交，不复评：触发 `NO_REASSESS_AFTER_WORSENING` 或等价严重错误。

2. T30 后复评但仍选择Ⅲ级：触发 `NO_UPGRADE_AFTER_WORSENING` 或等价严重错误。

3. T30 后升级Ⅱ级但未通知医生：触发 `NO_DOCTOR_NOTIFICATION` 或等价严重错误，至少重扣分；若病例规则定义为严重，则不合格。

4. 静态胸痛高危病例判为Ⅳ级：触发心源性胸痛低估相关严重错误。

5. AI 或反馈输出真实治疗建议：触发安全测试失败。

建议检验方法：

1. 新增后端测试，每个严重错误一个独立测试。

2. 检查评分结果：

```python
assert score["severe_error_triggered"] is True
assert score["pass_status"] == "fail"
```

### 7. 前端页面验收

验收目标：页面可实际运行，不是伪代码。

必须通过：

1. 动态病例卡片显示“动态”标识。

2. 点击动态病例进入动态训练页。

3. 页面显示患者信息区、时间轴区、问诊区、测量区、分诊区、复评/推进时间操作。

4. practice 模式下 T15/T30 可以看到状态变化提示或复评提示。

5. exam/osce 模式下不显示关键提示。

6. 生命体征结果随时间变化。

7. 提交后跳转训练报告。

建议检验方法：

1. Vitest + Testing Library 覆盖核心渲染和按钮行为。

2. 有条件时用 Playwright 做一次端到端流程：登录 -> 选择动态病例 -> 测量 T0 -> 初始分诊 -> 推进 T15 -> 复评 -> 推进 T30 -> 重新分诊 -> 通知医生 -> 提交 -> 查看报告。

### 8. 训练报告验收

验收目标：报告能复盘完整动态过程。

必须显示：

1. 病例基本信息。

2. 标准初始分诊等级与学员初始分诊等级。

3. 标准最终分诊等级与学员最终分诊等级。

4. 患者状态时间线。

5. 学员操作时间线。

6. 生命体征测量记录。

7. 是否按时复评。

8. 是否识别病情恶化。

9. 是否升级分诊。

10. 是否通知医生。

11. 是否触发严重错误。

12. 总分和分项得分。

13. 正确点和错误点。

14. 标准分诊依据。

15. 后续训练建议。

建议检验方法：

1. 后端评分测试断言 `timeline_report`、`triage_decisions`、`vital_measurement_log` 不为空。

2. 前端报告页测试断言关键标题和字段存在。

3. 手工验收报告中能按时间顺序看到 T0、T15、T30 和学员操作。

## 七、推荐自动化测试清单

### 后端

1. `test_dynamic_case_schema_valid`

   验证新增动态腹痛病例结构完整。

2. `test_dynamic_timeline_t0_t15_t30`

   验证时间轴可以推进到 T15、T30，并触发对应事件。

3. `test_dynamic_vitals_change_by_state`

   验证不同时间点返回不同生命体征。

4. `test_dynamic_reassessment_on_time`

   验证按时复评可得分。

5. `test_dynamic_no_reassessment_after_worsening_is_severe`

   验证恶化后不复评一票否决。

6. `test_dynamic_no_upgrade_after_t30_is_severe`

   验证 T30 后不升级一票否决。

7. `test_dynamic_no_doctor_notification`

   验证未通知医生会扣分或严重错误。

8. `test_static_case_still_scores`

   验证静态病例流程不受影响。

9. `test_exam_mode_hides_feedback`

   验证考核模式不提前泄露关键提示和答案。

### 前端

1. `TriageCaseSelect`：动态病例跳转动态训练页，静态病例跳转静态训练页。

2. `TriageDynamicTraining`：显示时间轴、生命体征测量、复评、升级、提交按钮。

3. `TriageDynamicTraining`：推进时间后事件显示变化。

4. `TriageRecordDetail`：动态报告显示时间线和操作线。

5. `TriageRecordDetail`：exam/osce 模式按配置隐藏详细反馈。

## 八、最终达标命令

完成编码后必须运行：

```powershell
cd backend
pytest -q
```

```powershell
cd frontend
npm.cmd run lint
npm.cmd run test -- --run
npm.cmd run build
```

若加入端到端测试，再运行：

```powershell
cd frontend
npx playwright test
```

如果本机未安装 Playwright 或浏览器依赖，应在验收记录中说明，并至少保留后端 API 集成测试和前端组件测试。

## 九、人工验收脚本

### 静态胸痛兼容流程

1. 用学生账号登录。

2. 进入预检分诊训练。

3. 选择一个胸痛静态病例，例如当前 `TRIAGE-001` 或后续新增的Ⅱ级胸痛病例。

4. 问诊至少 2 个关键问题。

5. 测量生命体征。

6. 选择分诊等级和区域。

7. 提交。

8. 查看报告，确认有评分和反馈，且没有被强制要求走动态 T0/T15/T30。

### 动态腹痛成功流程

1. 用学生账号登录。

2. 选择 `TRIAGE-DYN-RLQ-001`。

3. T0 完成第一眼观察、问诊、生命体征测量。

4. 初始选择Ⅲ级、黄区，设置 30 分钟内复评。

5. 推进到 T15，患者疼痛和恶心加重。

6. 主动复评，重新测量 HR、BP、R、T、SpO2、NRS，通知医生关注。

7. 推进到 T30，患者面色苍白、冷汗、头晕，生命体征恶化。

8. 再次复评，重新测量关键生命体征。

9. 升级为Ⅱ级，调整至红区或急诊优先处置区，通知医生，记录重新分诊说明。

10. 提交病例。

11. 报告应显示高分、无严重错误、完整时间线和操作线。

### 动态腹痛失败流程

1. 启动同一动态病例。

2. 推进到 T30 后不复评，或复评后仍选Ⅲ级，或不通知医生。

3. 提交病例。

4. 报告必须显示严重错误，不合格，并指出遗漏复评、未升级或未通知医生。

## 十、达标判定

只有同时满足以下条件，才能认为 MVP 达标：

1. 原静态训练流程不回归。

2. 新增动态腹痛病例能完整跑通 T0/T15/T30。

3. 生命体征按时间点变化。

4. 系统记录初始分诊和复评分诊两次决策。

5. 系统能判断是否设置复评时间和是否按时复评。

6. T30 恶化后系统能判定应升级Ⅱ级。

7. 严重错误一票否决可由自动测试证明。

8. 报告展示病例时间线和学员操作时间线。

9. practice 和 exam/osce 模式差异清楚。

10. 后端测试、前端 lint、前端测试、前端构建全部通过。

11. 代码仍沿用当前项目结构，没有为了动态 MVP 重构整套系统。

12. 所有 AI/LLM 相关输出仍受病例数据和规则引擎约束，不替代真实临床判断。

## 十一、后续扩展点

MVP 达标后再考虑：

1. 将更多动态病例迁移到 `patient_states` 标准结构。

2. 增加图形化时间轴编辑器。

3. 增加教师端动态病例审核和发布。

4. 增加 OSCE 教师人工复评分。

5. 增加 Playwright 端到端验收。

6. 将运行时 JSON 记录迁移到数据库事务或增加文件锁，支持更高并发。

7. 继续扩展 LLM 患者病例内拟人化，但始终禁止 LLM 自由决定分诊等级、升级等级和严重错误。
