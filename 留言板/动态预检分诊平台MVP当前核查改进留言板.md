# 动态预检分诊平台 MVP 当前核查改进留言板

核查日期：2026-06-20

核查依据：`留言板/动态预检分诊平台MVP实施验收留言板.md`

核查目标：检查当前系统是否已经达到动态预检分诊平台 MVP 的实施与验收要求，记录遗漏、未达标和仍需精进的点，并给出详细修改方法、步骤和再次验收方法。

结论：当前系统已经明显推进到“可运行的动态 MVP 雏形”：新增了动态腹痛病例、状态机模块、时间轴扩展、动态评分、动态训练页、动态报告和自动化测试；后端与前端基础命令均通过。但是还不能判定完全达标，主要卡点是：动态答案泄露到学生端、状态机未真正接入流程、组合血压未随时间变化、复评按时标志错误、训练记录复盘信息丢失、前端/后端测试覆盖不够硬。

## 一、已核查的当前证据

### 1. 已存在的关键新增内容

1. 动态病例：`backend/triage_data/cases_dynamic/TRIAGE-DYN-RLQ-001.json` 已存在。

2. 状态机模块：`backend/services/triage_state_machine.py` 已存在。

3. 时间轴模块：`backend/services/triage_timeline.py` 已扩展，支持 `patient_states`、事件类型、训练/考核提示字段、当前患者状态、分诊决策记录和学员操作记录。

4. 复评模块：`backend/services/triage_reassessment.py` 已存在。

5. 动态评分：`backend/services/triage_scoring_v4.py` 已支持动态评分维度、动态严重错误和时间线报告。

6. 动态接口：`backend/routers/triage.py` 已有 `/timeline`、`/timeline/advance`、`/reassess`、`/upgrade`、`/initial-decision`、`/notify-doctor`、`/save-notes`。

7. 前端动态训练页：`frontend/src/pages/triage/TriageDynamicTraining.jsx` 已支持测量、推进时间、复评、记录初始分诊、通知医生、记录说明、提交。

8. 前端时间轴组件：`frontend/src/components/triage/TriageTimelinePanel.jsx` 已显示 T0/T15/T30 风格的横向时间轴。

9. 动态报告：`frontend/src/pages/triage/TriageRecordDetail.jsx` 已新增动态时间线报告和生命体征测量记录展示。

10. 测试文件：`backend/tests/test_triage_dynamic_mvp.py` 和 `frontend/src/__tests__/TriageDynamicTraining.test.jsx` 已存在。

### 2. 自动化验证结果

已运行：

```powershell
cd backend
pytest -q
```

结果：52 passed，11 warnings。警告主要包括 Pydantic v2 `class Config` 弃用和 `.pytest_cache` 写入警告。

已运行：

```powershell
cd frontend
npm.cmd run lint
npm.cmd run test -- --run
npm.cmd run build
```

结果：

1. lint 通过。

2. Vitest 通过：4 个测试文件，26 个测试。

3. build 通过。

### 3. API 级流程复核结果

使用 TestClient 走通了动态病例 `TRIAGE-DYN-RLQ-001`：

1. 启动病例成功。

2. T0/T15/T30 推进成功。

3. 心率和疼痛评分会随时间变化。

4. 能记录初始分诊和复评分诊两次决策。

5. 通知医生可记录。

6. 提交后可生成动态时间线报告。

但同时发现：

1. `current_stage` 从 T0 到 T30 一直是 `ARRIVAL`。

2. 血压在 T0/T15/T30 都返回 `118/74`，未体现 T15 的 `108/68` 和 T30 的 `96/60`。

3. 成功复评并升级后，报告中 `reassessment_on_time` 仍为 `False`。

4. 患者 T15/T30 时间轴事件消息没有持久化到训练记录 `messages`。

5. `measure_vitals` 没有稳定写入 `student_actions`，报告操作线缺少测量动作。

6. `get_case_safe("TRIAGE-DYN-RLQ-001")` 会泄露标准等级、标准区域、`patient_states`、动态评分标准、动态严重错误和动态反馈。

## 二、已基本达标的部分

### 1. 动态病例 MVP 数据已建立

当前 `TRIAGE-DYN-RLQ-001` 已满足大部分数据要求：

1. `is_dynamic=true`。

2. `dynamic_timeline.enabled=true`。

3. 有 T0、T15、T30 三个患者状态。

4. T0 标准等级为Ⅲ级、区域黄区。

5. T30 标准等级为Ⅱ级、区域红区。

6. 有动态评分维度，合计 100 分。

7. 有动态严重错误清单。

8. 有动态反馈字段。

但数据仍需要修补，详见后续 P1 项。

### 2. 后端动态接口已具备雏形

动态训练所需接口基本齐全，不需要推倒重写：

1. 启动病例。

2. 获取时间轴。

3. 推进时间。

4. 测量生命体征。

5. 记录初始分诊。

6. 复评。

7. 升级分诊。

8. 通知医生。

9. 保存记录说明。

10. 提交评分。

后续重点应放在“接严、脱敏、修正记录一致性和补强测试”，不是再新造一套接口。

### 3. 前端动态训练和报告页面已能构成可运行雏形

前端已具备：

1. 动态病例入口。

2. 动态训练页面。

3. 生命体征测量选择。

4. 时间推进。

5. 复评按钮。

6. 初始分诊记录。

7. 通知医生。

8. 记录说明。

9. 动态报告展示。

后续重点是训练/考核模式脱敏、交互测试、UI 状态分离和复盘完整性。

## 三、P0 必须优先修复的问题

### P0-1：动态病例标准答案泄露到学生端

证据：

`get_case_safe("TRIAGE-DYN-RLQ-001")` 当前仍返回以下敏感字段：

1. `standard_initial_triage_level`

2. `standard_final_triage_level`

3. `standard_initial_area`

4. `standard_final_area`

5. `patient_states`

6. `dynamic_scoring_rubric`

7. `dynamic_severe_errors`

8. `dynamic_feedback`

9. `required_dynamic_actions`

影响：

这会让学生端直接拿到标准初始等级、最终等级、严重错误、评分规则、标准反馈和推荐动作。练习模式也会削弱训练价值，考核模式则直接不达标。

修改方法：

1. 在 `backend/services/triage_repository.py` 中扩展 `get_case_safe()` 的脱敏列表。

2. 对动态病例新增专门的安全化函数，例如 `sanitize_dynamic_case_for_student(case)`。

3. 从学生端安全病例中移除：

   - `standard_initial_triage_level`
   - `standard_final_triage_level`
   - `standard_initial_area`
   - `standard_final_area`
   - `dynamic_scoring_rubric`
   - `dynamic_severe_errors`
   - `dynamic_feedback`
   - `required_dynamic_actions`

4. `patient_states` 不应原样返回。若前端确实需要患者外观，应只返回当前状态的非标准字段，并去掉：

   - `standard_triage_level`
   - `standard_area`
   - `recommended_actions`
   - `risk_signals` 中过于答案化的内容

5. `dynamic_timeline` 返回给学生端时只保留安全摘要，不返回完整事件、标准等级、严重错误和 expected actions。

建议测试：

1. 扩展 `backend/tests/test_triage_case_safe_redaction.py`，新增 `TRIAGE-DYN-RLQ-001` 专项脱敏测试。

2. 断言安全病例中不存在上述敏感字段。

3. 对 exam/osce 模式再做一次 API 测试，确认病例详情接口不会泄露标准答案。

验收标准：

`get_case_safe("TRIAGE-DYN-RLQ-001")` 不再返回任何标准等级、标准区域、评分规则、严重错误、标准反馈或推荐动作。

### P0-2：考核模式时间轴仍泄露关键提示和严重错误提示

证据：

`get_timeline()` 当前直接返回 `state.timeline_events`。即使 `advance_timeline()` 在 exam/osce 模式清空了 `student_prompt`，`get_timeline()` 仍可能把以下字段返回给前端：

1. `requires_reassessment`

2. `expected_student_actions`

3. `standard_level_after_event`

4. `severe_error_if_ignored`

5. `severe_error_code`

6. `consequence_if_missed`

前端 `TriageTimelinePanel.jsx` 还会显示“需要复评”和“忽略将触发严重错误”。

影响：

考核模式应只展示患者自然表现变化，不应主动告诉学生“需要复评”“忽略会严重错误”。当前不满足 MVP 留言板的 exam/osce 模式要求。

修改方法：

1. 在 `backend/services/triage_timeline.py` 中新增 `sanitize_timeline_events_for_mode(events, mode)`。

2. practice 模式可返回 `student_prompt`、`requires_reassessment` 等训练提示。

3. exam/osce 模式只返回：

   - `event_id`
   - `scheduled_minute`
   - `event_type`
   - `triggered`
   - `event_description` 或患者自然表现
   - `patient_expression`

4. exam/osce 模式必须移除：

   - `student_prompt`
   - `expected_student_actions`
   - `standard_level_after_event`
   - `severe_error_if_ignored`
   - `severe_error_code`
   - `consequence_if_missed`
   - 显式 `requires_reassessment` 提示

5. `TriageTimelinePanel.jsx` 根据 `timeline.mode` 或后端返回字段决定是否显示复评提示。

建议测试：

1. 后端新增 `test_exam_timeline_does_not_leak_hints`。

2. 前端新增 exam 模式渲染测试，断言页面不出现“需要复评”“严重错误”“应升级”等提示文案。

验收标准：

exam/osce 模式下，学生只能看到患者表现变化，不能看到标准动作、严重错误和复评提示。

### P0-3：患者状态机模块存在，但没有真正接入训练流程

证据：

`backend/services/triage_state_machine.py` 已存在，但当前核查没有发现路由或时间轴模块实际调用 `create_state_machine()` 或 `PatientStateMachine.transition()`。

API 流程验证结果：

1. 启动病例后 `current_stage=ARRIVAL`。

2. 初始分诊后仍是 `ARRIVAL`。

3. 推进到 T15 后仍是 `ARRIVAL`。

4. 推进到 T30 后仍是 `ARRIVAL`。

5. 复评、升级、通知医生、提交后也未体现完整状态推进。

影响：

MVP 留言板要求“患者状态机不是静态展示，必须根据操作和模拟时间推进”。当前只是有模块和字段，未证明状态机驱动流程，因此状态机验收不达标。

修改方法：

1. 在 `backend/routers/triage.py` 的关键动作中调用状态机：

   - start：`start_training`
   - observe：`first_look`
   - message：`start_history`
   - measure：`measure_vitals`
   - initial-decision：`initial_triage` 后 `wait`
   - timeline/advance：根据事件触发 `advance_time`、`reassessment_due`、`deteriorated`
   - reassess：`reassess`
   - upgrade：`re_triage`
   - notify-doctor：`notify_doctor`
   - save-notes：`record_notes`
   - submit：`submit`

2. 统一时间字段。当前状态机使用 `simulation_minute`，时间轴使用 `current_simulated_minute`。建议统一为 `current_simulated_minute`，或在状态机中读取兼容字段。

3. 状态机每次转移后必须写入：

   - `timeline_state.current_stage`
   - `timeline_state.stage_history`
   - `timeline_state.system_events`

4. 时间轴事件触发复评或恶化时，应更新 `current_stage`：

   - T15 可进入 `REASSESSMENT_DUE`
   - T30 应进入 `DETERIORATED`

建议测试：

1. 后端新增 `test_state_machine_stage_transitions_dynamic_mvp`。

2. 断言 start -> observe -> measure -> initial-decision -> advance T15 -> advance T30 -> reassess -> upgrade -> notify -> submit 的状态序列。

验收标准：

完整动态流程结束后，`stage_history` 能复盘所有关键状态，提交后 `current_stage=COMPLETED`。

### P0-4：动态血压没有随 T15/T30 变化

证据：

API 级验证中测量 `heart_rate`、`blood_pressure`、`pain_score`：

1. T0：HR 94，BP 118/74，NRS 5。

2. T15：HR 108，BP 118/74，NRS 7。

3. T30：HR 122，BP 118/74，NRS 8。

心率和疼痛评分已变化，但血压仍停留在初始值。病例数据中的 T15/T30 已有：

1. T15：`blood_pressure_systolic=108`，`blood_pressure_diastolic=68`。

2. T30：`blood_pressure_systolic=96`，`blood_pressure_diastolic=60`。

原因：

测量接口请求的是 `blood_pressure`，而 `patient_states.vital_signs` 存的是 `blood_pressure_systolic` 和 `blood_pressure_diastolic`。当前映射没有把两个字段组合成 `blood_pressure`。

影响：

不满足“同一测量项目在不同时间点返回对应时间点结果”的动态生命体征验收要求，尤其血压是本病例识别恶化的关键指标。

修改方法：

1. 在 `backend/routers/triage.py` 的动态测量逻辑中新增标准化函数，例如：

```python
def resolve_dynamic_vital_value(mid, current_vitals):
    if mid == "blood_pressure":
        sbp = current_vitals.get("blood_pressure_systolic") or current_vitals.get("systolic_bp_mmhg")
        dbp = current_vitals.get("blood_pressure_diastolic") or current_vitals.get("diastolic_bp_mmhg")
        if sbp is not None and dbp is not None:
            return f"{sbp}/{dbp}"
    return current_vitals.get(mid)
```

2. 同时兼容旧字段：

   - `heart_rate` / `heart_rate_bpm`
   - `respiratory_rate` / `respiratory_rate_bpm`
   - `spo2` / `spo2_percent`
   - `temperature`
   - `pain_score`

3. 将该逻辑抽到服务层，避免路由里堆字段映射。

4. 补充 T15 和 T30 的 `spo2`。用户要求 T15 SpO2 98%，T30 SpO2 97%，当前 T15/T30 patient state 未写完整。

建议测试：

1. 修改 `test_dynamic_vitals_change_by_state`，强断言：

   - T0 BP = `118/74`
   - T15 BP = `108/68`
   - T30 BP = `96/60`
   - T30 SpO2 = `97`

2. 前端测试断言测量结果区显示 T30 血压 `96/60`。

验收标准：

T0/T15/T30 的 HR、BP、R、T、SpO2、NRS 均按病例状态返回。

## 四、P1 需要尽快完善的问题

### P1-1：成功复评后报告仍显示“未按时复评”

证据：

API 成功路径中，T30 后复评、升级Ⅱ级、通知医生，报告标志为：

1. `deterioration_recognized=True`

2. `triage_upgraded=True`

3. `doctor_notified=True`

4. `reassessment_on_time=False`

原因：

`triage_scoring_v4.py` 的报告使用 `state.get("reassessment_completed")` 和 `state.get("reassessment_overdue")` 判定，但 `triage_reassessment.py` 创建复评后没有设置 `reassessment_completed=True`。另外按时复评应基于复评记录的 minute 与 due minute 比较，而不是只看一个全局布尔。

修改方法：

1. 在 `create_reassessment()` 中设置：

```python
state["reassessment_completed"] = True
state["last_reassessment_minute"] = current_minute
```

2. 在 `evaluate_reassessment()` 中返回 `on_time` 后，将结果写回对应复评记录。

3. 报告中 `reassessment_on_time` 应从 `reassessments` 或 `triage_decisions` 计算：

   - 初始Ⅲ级要求 30 分钟内复评。
   - 如果 T15 发生症状加重，应允许提前复评。
   - T30 恶化后，复评应视为“恶化后及时复评”，不要与初始 due 混用。

4. 如需严格区分，报告可拆成：

   - `initial_reassessment_set`
   - `reassessment_after_T15`
   - `reassessment_after_T30`
   - `reassessment_overdue`

建议测试：

1. 成功路径断言 `reassessment_on_time=True` 或至少 `reassessment_after_deterioration=True`。

2. 逾期路径断言 `reassessment_overdue=True`。

### P1-2：动态事件患者消息没有持久化到训练记录

证据：

启动 `TRIAGE-DYN-RLQ-001` 后推进到 T15，训练记录 `messages` 仍只有开场白，没有 T15 患者状态变化消息。

原因：

`advance_timeline()` 中先调用 `append_message(record_id, ...)` 保存消息，再 `_save_record(record)` 保存旧 record，可能用旧 messages 覆盖掉刚追加的消息。

影响：

前端当场可能通过接口返回看到事件，但训练记录和报告复盘缺少患者恶化时的对话/表现证据。

修改方法：

1. 不要在同一路由里混用“按 record_id 重新加载保存”和“当前 record 对象保存”。

2. 新增一个只修改当前 record 对象的函数，例如：

```python
def append_message_to_record(record, role, content):
    record.setdefault("messages", []).append({...})
    return record
```

3. `advance_timeline()` 中统一对当前 record 追加消息、记录 action、更新时间轴，最后只 `_save_record(record)` 一次。

4. 或者在 `append_message()` 后重新加载 record，再继续写入时间轴，避免覆盖。

建议测试：

1. 推进到 T15 后获取 record，断言 `messages` 至少包含 T15 患者表达。

2. 推进到 T30 后获取 record，断言 `messages` 包含 T30 恶化表达。

### P1-3：测量生命体征未稳定写入 `student_actions`

证据：

动态流程报告中的 `student_actions` 包含 initial_triage、advance_time、reassess、notify_doctor，但没有 measure_vitals。

原因：

动态测量分支里先 `_save_record(record)`，再 `record_student_action(record, "measure_vitals", ...)`，随后又调用 `record_action(record_id, ...)` 重新加载并保存 record，导致 `record_student_action` 的修改可能丢失。

影响：

训练报告中的“学员操作时间线”不完整，无法证明学生在 T0/T15/T30 进行了哪些测量。

修改方法：

1. 将 `record_student_action(record, "measure_vitals", ...)` 放到 `_save_record(record)` 之前。

2. 避免随后 `record_action()` 覆盖当前对象。可以把 `measured_vitals` 更新也直接在当前 record 上完成。

3. 将测量结果、测量项目、模拟时间统一写入：

   - `student_actions`
   - `vital_measurement_log`
   - `measured_vitals`

建议测试：

1. T0/T15/T30 各测量一次后，`student_actions` 中应有 3 条 `measure_vitals`。

2. 报告 `timeline_nodes` 的 `student_action` 应能显示测量动作。

### P1-4：动态病例事件 `patient_state_id` 与实际状态 ID 不一致

证据：

`TRIAGE-DYN-RLQ-001.json` 中：

1. `patient_states` 包含 `T15_event_1`、`T30_event_2`。

2. `dynamic_timeline.events` 引用的是 `T15_worsening`、`T30_deteriorated`。

当前之所以能匹配，是因为 `_get_patient_state()` fallback 按 minute 找最近状态。

影响：

这属于隐性脆弱点。后续病例如果同一分钟多个状态或时间变化更复杂，会出现状态错配。

修改方法：

1. 统一 ID：

   - T15 event 引用 `T15_event_1`
   - T30 event 引用 `T30_event_2`

2. 或者把 patient_states 的 state_id 改成 `T15_worsening`、`T30_deteriorated`。

3. 新增病例 schema 校验，断言所有 `event.patient_state_id` 都能在 `patient_states.state_id` 中找到。

建议测试：

`test_dynamic_case_schema_valid` 增加：

```python
state_ids = {s["state_id"] for s in data["patient_states"]}
for ev in data["dynamic_timeline"]["events"]:
    assert ev["patient_state_id"] in state_ids
```

### P1-5：T15/T30 患者状态字段不完整

证据：

T15/T30 的 `state_name`、`chief_complaint`、`symptom_description` 为空或过于泛化，`appearance` 未体现“坐不住、面色苍白、冷汗、头晕”等关键变化。T15/T30 也缺少 SpO2。

影响：

这会削弱“患者外观、主诉、回答内容和生命体征动态更新”的训练目标。

修改方法：

1. T15：

   - `state_name`: 疼痛和恶心加重
   - `appearance`: 坐立不安、右下腹疼痛明显
   - `chief_complaint`: “疼得更厉害了，还有点恶心”
   - `symptom_description`: 疼痛从 NRS 5 升至 7，恶心加重，生命体征开始恶化
   - `spo2`: 98

2. T30：

   - `state_name`: 明显恶化伴循环不稳定表现
   - `appearance`: 面色苍白、额部冷汗、诉头晕
   - `chief_complaint`: “我头晕，疼得受不了了”
   - `symptom_description`: HR 122、BP 96/60、NRS 8，提示休克早期风险
   - `spo2`: 97

3. T15 的 `recommended_actions` 应为提前复评、重新测量、通知医生关注、缩短复评间隔，不应直接写“升级分诊等级”，因为 T15 标准仍为Ⅲ级。

建议测试：

病例 schema 测试断言 T15/T30 的 `state_name`、`appearance`、`chief_complaint`、`symptom_description` 非空，并含关键变化词。

### P1-6：动态成功路径测试不够硬

证据：

当前 `test_dynamic_reassessment_on_time_does_not_trigger_severe` 只断言“不触发严重错误”，没有断言：

1. `reassessment_on_time=True`

2. `triage_upgraded=True`

3. `doctor_notified=True`

4. `student_actions` 包含测量、复评、通知医生。

5. T15/T30 血压和 SpO2 正确变化。

`test_dynamic_no_doctor_notification_deducts` 的断言也偏弱：`score < 100` 很容易成立，不能证明“未通知医生”真的被识别。

修改方法：

1. 成功路径测试要断言报告四个标志均正确。

2. 未通知医生测试必须断言出现 `NO_DOCTOR_NOTIFICATION` 或明确扣分字段。

3. 动态生命体征测试必须覆盖血压、呼吸、SpO2、体温、NRS。

4. 状态机测试必须断言阶段变化，不只断言接口 200。

### P1-7：前端动态训练测试只是导入测试，缺少真实交互

证据：

`frontend/src/__tests__/TriageDynamicTraining.test.jsx` 当前主要验证 API 函数存在、组件模块可导入，没有渲染页面、没有点击、没有测量、没有推进时间、没有复评、没有提交。

影响：

前端测试通过不能证明动态训练页达标。

修改方法：

1. 使用 Testing Library 渲染 `TriageDynamicTraining`，mock API 返回动态病例和时间轴。

2. 测试以下交互：

   - 显示患者信息区。
   - 显示 T0/T15/T30 时间轴。
   - 选择测量项并点击测量。
   - 点击记录初始分诊。
   - 推进到 T15/T30。
   - 点击复评。
   - 点击通知医生。
   - 点击提交后跳转报告。

3. 增加 exam/osce 模式测试，确认不显示“需要复评”“严重错误”等提示。

4. 有条件时补 Playwright 端到端测试。

## 五、P2 可后续精进的问题

### P2-1：未专家审核的动态病例已出现在学生病例列表

证据：

`TRIAGE-DYN-RLQ-001` 的 `review_status.approved_for_training=false`，但 `list_cases()` 当前不按审核状态过滤病例。

影响：

MVP 测试可用没问题，但正式训练/考核库不应向学生开放未审核病例。

修改方法：

1. 增加开发/草稿病例可见性规则：

   - 教师可见草稿。
   - 学生默认只看 `approved_for_training=true` 或明确 `stage=ACTIVE` 的病例。
   - MVP 调试病例可通过 `?include_draft=true` 或教师任务发布方式开放。

2. 如果为了当前 MVP 演示必须让学生看到该病例，应把页面清楚标识为“待审核训练样例”，并禁止进入正式考试任务。

建议测试：

学生列表不显示未审核病例；教师列表显示并标注审核状态。

### P2-2：`/current-state` 没有传入病例数据，返回信息不完整

证据：

`get_current_state()` 调用 `get_current_patient_state(record)`，没有传入 `case`。因此它无法返回 `patient_state_id`、`state_name`、`state_vitals`、标准字段等完整上下文。

修改方法：

1. 在 `get_current_state()` 中加载病例：

```python
case = get_case(record.get("case_external_id", ""))
return get_current_patient_state(record, case)
```

2. 学生端返回仍要脱敏，不能返回标准等级和标准区域。

### P2-3：前端动态训练页的交互仍偏 MVP，护理流程语义不够清楚

问题：

1. `selectedLevel` 同时用于初始分诊和复评分诊，容易让学生混淆当前选择是在记录初始分诊还是最终分诊。

2. 初始复评时间固定为 30 分钟，不能由学生输入或选择。

3. 复评 payload 中未从 UI 显式传递 `notify_doctor`。

4. `handleSaveNotes()` 使用浏览器 `prompt()`，不适合正式训练界面。

5. 未单独显示“当前患者外观/当前状态/当前主诉”区域，只在时间轴中有部分提示。

修改方法：

1. 分离状态：

   - `initialLevel`
   - `initialZone`
   - `reassessmentLevel`
   - `reassessmentZone`
   - `reassessmentInterval`
   - `doctorNotified`

2. 增加复评时间选择控件，例如 10/15/30/60 分钟。

3. 通知医生用 checkbox 或 toggle 明确记录，并进入复评 payload。

4. 把记录说明改成页面内 textarea 或 modal。

5. 在患者信息区展示当前状态字段。

### P2-4：训练报告仍缺少更完整的“学员操作时间线”

当前已有报告结构，但受前述日志问题影响，测量动作、患者消息、记录说明等不稳定。修复 P1-2 和 P1-3 后，还应进一步：

1. 按时间顺序合并：

   - 系统事件
   - 患者状态变化
   - 学员问诊
   - 生命体征测量
   - 初始分诊
   - 复评
   - 升级
   - 通知医生
   - 记录说明
   - 提交

2. 报告中标注哪些操作是及时完成，哪些遗漏。

3. 教师端导出时保留同一时间线。

### P2-5：测试运行有警告需要后续清理

当前 `pytest` 有 11 个 warning：

1. Pydantic v2 `class Config` 弃用。

2. `.pytest_cache` 创建路径警告。

修改方法：

1. 逐步把 schemas 中的 class Config 改为 `model_config = ConfigDict(...)`。

2. 清理或修复 `.pytest_cache` 目录问题，避免 CI 中出现噪声。

## 六、建议修复顺序

1. P0-1：先修动态安全脱敏，防止答案泄露。

2. P0-2：修 exam/osce 时间轴提示泄露。

3. P0-3：把状态机真正接入路由流程。

4. P0-4：修动态血压和完整生命体征映射。

5. P1-1：修按时复评判定。

6. P1-2/P1-3：修消息和学员操作日志持久化。

7. P1-4/P1-5：修病例数据 ID 和患者状态完整性。

8. P1-6/P1-7：补硬测试和前端交互测试。

9. P2：处理审核可见性、current-state、前端体验和测试警告。

## 七、再次验收方法

### 1. 必跑命令

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

### 2. 必加自动化断言

后端至少新增或加强以下断言：

1. `get_case_safe("TRIAGE-DYN-RLQ-001")` 不泄露标准等级、评分规则、严重错误、标准反馈。

2. exam/osce 模式 `/timeline` 不返回复评提示、严重错误提示和 expected actions。

3. 状态机能从 ARRIVAL 推进到 COMPLETED。

4. T0/T15/T30 的 BP、HR、R、T、SpO2、NRS 都正确变化。

5. 成功路径报告：

   - `reassessment_on_time=True`
   - `deterioration_recognized=True`
   - `triage_upgraded=True`
   - `doctor_notified=True`
   - `severe_error_triggered=False`

6. 未通知医生路径明确出现 `NO_DOCTOR_NOTIFICATION` 或等价扣分。

7. 推进 T15/T30 后，训练记录 messages 保留患者状态变化消息。

8. T0/T15/T30 测量后，`student_actions` 包含 3 条 `measure_vitals`。

前端至少新增：

1. 动态训练页真实渲染测试。

2. 测量、推进时间、复评、通知医生、提交的交互测试。

3. exam/osce 模式不显示关键提示的测试。

4. 动态报告页显示初始/最终分诊、生命体征记录、时间线和四个关键标志的测试。

### 3. API 级人工复核脚本要看到的结果

修复后再次跑动态成功流程，应看到：

1. T0 BP = `118/74`。

2. T15 BP = `108/68`。

3. T30 BP = `96/60`。

4. `current_stage` 随流程变化，提交后为 `COMPLETED`。

5. 成功路径无严重错误。

6. 报告标志：

   - `reassessment_on_time=True`
   - `deterioration_recognized=True`
   - `triage_upgraded=True`
   - `doctor_notified=True`

7. `student_actions` 包含 measure、initial_triage、advance_time、reassess、upgrade_triage、notify_doctor、record_notes、submit。

8. `messages` 包含开场白、T15 变化、T30 恶化。

### 4. 达标判定

只有当以下全部满足，才能认为当前系统达到 MVP 留言板要求：

1. 所有必跑命令通过。

2. 动态病例数据完整且不泄露标准答案。

3. 状态机真实驱动流程并留下 stage history。

4. 动态生命体征完整随时间变化。

5. 初始分诊和复评分诊分别记录。

6. 复评及时性判定正确。

7. 严重错误路径由强断言测试覆盖。

8. 训练报告能完整复盘患者状态时间线和学员操作时间线。

9. practice 和 exam/osce 模式差异正确。

10. 未专家审核病例不会误入正式学生训练或考试库。

## 八、本次核查结语

当前系统的方向是对的，已经从“计划文档”推进到了可运行的动态 MVP 雏形。但验收不能只看测试绿灯。真正影响达标的地方集中在四个字：脱敏、状态、生命体征、复盘。优先修复 P0/P1 后，再补强测试，系统就会从“能演示”更稳地走到“能教学验收”。
