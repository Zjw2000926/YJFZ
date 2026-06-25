# 动态预检分诊平台 MVP 验收未达标修复留言板

更新时间：2026-06-20

用途：记录本次核查验收后仍未达标的修复点、建议修复方法、实施步骤和最终验收方法。本文只作为开发留言板和执行清单，不替代病例专家审核。

验收结论：当前系统已具备动态病例主流程 MVP 能力，但尚未达到严格验收标准。核心未达标点集中在考核模式脱敏、患者状态机真实推进、动态病例学生入口、学生操作日志完整性和测试覆盖强度。

## 一、当前已达标证据

以下能力已具备，可作为后续修复时的回归保护基线：

1. 后端测试可通过：在 `backend` 目录执行 `pytest -q`，当前结果为 `57 passed, 1 warning`。
2. 前端 lint 可通过：在 `frontend` 目录执行 `npm run lint`。
3. 前端单元测试可通过：在 `frontend` 目录执行 `npm run test -- --run`，当前结果为 `26 passed`。
4. 前端生产构建可通过：在 `frontend` 目录执行 `npm run build`。
5. 本地服务 smoke 可通过：后端 `127.0.0.1:8010`、前端 `127.0.0.1:3010` 可启动，前端代理 `/api/auth/login` 可登录成功。
6. 动态腹痛病例可用 external id 直接启动并完成训练流程。
7. 动态生命体征已按 T0/T15/T30 返回不同结果：
   - T0：BP `118/74`，HR `94`，NRS `5`。
   - T15：BP `108/68`，HR `108`，NRS `7`。
   - T30：BP `96/60`，HR `122`，NRS `8`。
8. 正确完成复评、升级、通知医生后，动态报告能标记：
   - `reassessment_on_time=true`
   - `deterioration_recognized=true`
   - `triage_upgraded=true`
   - `doctor_notified=true`
9. 病例详情安全接口 `get_case_safe()` 已基本移除动态病例顶层标准答案和评分规则字段。

## 二、P0 必须修复项

### P0-1 考核模式 `/timeline` 仍泄露标准答案

问题现象：

考核模式下，`/api/triage/training/{record_id}/timeline` 的 `timeline_events` 已经做了脱敏，但同一响应中的 `patient_state` 仍包含以下敏感字段：

- `standard_triage_level`
- `standard_area`
- `recommended_actions`
- `state_vitals`

这会导致考核模式直接暴露标准分诊等级、标准区域和推荐操作，不符合“考核模式不主动提示关键答案”的要求。

涉及文件：

- `backend/services/triage_timeline.py`
- `backend/routers/triage.py`
- `backend/tests/test_triage_dynamic_mvp.py`

建议修复方法：

1. 在 `backend/services/triage_timeline.py` 中新增患者状态脱敏函数，例如：
   - `sanitize_patient_state_for_mode(patient_state: dict, mode: str) -> dict`
2. practice/training 模式可以保留较完整状态信息，但仍建议不要返回标准答案字段到普通学生端。
3. exam/osce 模式必须移除以下字段：
   - `standard_triage_level`
   - `standard_area`
   - `recommended_actions`
   - `state_vitals`
   - 任何 `standard_*`
   - 任何 `expected_*`
   - 任何 `severe_error_*`
4. 对 exam/osce 模式，只保留学员可自然观察到的信息：
   - `minute`
   - `stage`
   - `expression`
   - `appearance`
   - `vitals` 是否保留要按当前训练设计决定；如果生命体征需要点击测量后才显示，则 `/timeline` 中也不应直接返回完整 `vitals`。
   - `reassessment_due`
   - `deteriorated`
   - `patient_state_id` 可选，若前端不需要，建议不返回。
5. 在 `backend/routers/triage.py` 的 `get_timeline()` 中，对 `patient_state` 调用该脱敏函数后再返回。
6. 同步检查 `/training/{record_id}/current-state` 接口，避免它在 exam/osce 模式下绕过 `/timeline` 脱敏。

建议测试：

1. 在 `backend/tests/test_triage_dynamic_mvp.py` 新增测试：
   - 启动 `TRIAGE-DYN-RLQ-001`，mode 使用 `exam`。
   - 推进到 T30。
   - 请求 `/timeline`。
   - 断言 `timeline_events` 不含 `student_prompt`、`expected_student_actions`、`standard_level_after_event` 等字段。
   - 断言 `patient_state` 不含 `standard_triage_level`、`standard_area`、`recommended_actions`、`state_vitals`。
2. 再请求 `/current-state`，同样断言不泄露上述字段。

验收方法：

执行：

```powershell
cd backend
pytest -q tests/test_triage_dynamic_mvp.py
```

接口抽查：

1. 用 `student1/123456` 登录。
2. exam 模式启动 `TRIAGE-DYN-RLQ-001`。
3. 推进到 T30。
4. 检查 `/api/triage/training/{record_id}/timeline` 响应。
5. 响应中不得出现标准等级、标准区域、推荐动作、严重错误答案和评分依据。

达标标准：

- exam/osce 模式下学生接口不返回任何标准答案字段。
- practice 模式如保留教学提示，必须有明确 mode 分支，不能误用于 exam/osce。

### P0-2 患者状态机未真正推进到完整训练阶段

问题现象：

动态病例完整跑完后，`timeline_state.current_stage` 仍停在 `INITIAL_VITALS`，`stage_history` 为 `None`。这说明状态机模块存在，但没有真正贯穿训练流程。

当前未可靠覆盖的阶段包括：

- `INITIAL_TRIAGE`
- `WAITING`
- `REASSESSMENT_DUE`
- `DETERIORATED`
- `REASSESSMENT`
- `RE_TRIAGE`
- `FINAL_DISPOSITION`
- `COMPLETED`

涉及文件：

- `backend/services/triage_state_machine.py`
- `backend/services/triage_timeline.py`
- `backend/routers/triage.py`
- `backend/tests/test_triage_dynamic_mvp.py`

建议修复方法：

1. 修复 `PatientStateMachine.__init__()`：
   - 当前 `timeline_state` 已存在时不会补齐 `stage_history`、`system_events` 等字段。
   - 应在任何情况下使用 `setdefault()` 补齐：
     - `current_stage`
     - `stage_history`
     - `system_events`
     - `current_simulated_minute`
     - `reassessment_completed`
     - `reassessment_overdue`
     - `deteriorated`
2. 统一时间字段：
   - 当前状态机使用 `simulation_minute`。
   - 时间轴使用 `current_simulated_minute`。
   - 建议统一为 `current_simulated_minute`，或状态机兼容读取两个字段，但写入一个主字段。
3. 在关键 API 中调用状态机 transition：
   - `/training/start`：初始化后进入 `ARRIVAL` 或 `FIRST_LOOK`。
   - `/observe`：触发 `first_look`，推进到 `FIRST_LOOK`。
   - `/message` 或问诊动作：触发 `ask_question`，推进到 `HISTORY_TAKING`。
   - `/measure`：触发 `measure_vitals`，推进到 `INITIAL_VITALS`。
   - `/initial-decision`：触发 `initial_triage`，推进到 `INITIAL_TRIAGE`，随后进入 `WAITING`。
   - `/timeline/advance`：到达复评时间时推进到 `REASSESSMENT_DUE`；出现恶化事件时推进到 `DETERIORATED`。
   - `/reassess`：推进到 `REASSESSMENT`。
   - `/upgrade` 或复评时选择升级：推进到 `RE_TRIAGE`。
   - `/notify-doctor`、`/save-notes`：推进或保持在 `FINAL_DISPOSITION` 相关阶段。
   - `/submit`：推进到 `COMPLETED`。
4. 对非法状态转移不要静默忽略：
   - 可记录 `system_events`，说明某动作在当前阶段未触发阶段变化。
   - 不建议直接报错阻断旧流程，避免破坏静态训练兼容。
5. 在训练报告中显示 `stage_history`，用于审计学员流程路径。

建议测试：

新增或加强状态机测试：

1. 启动动态病例。
2. 完成观察、问诊、测量、初始分诊。
3. 断言阶段进入 `WAITING`。
4. 推进到 T15，断言阶段进入 `REASSESSMENT_DUE` 或相关候诊复评状态。
5. 推进到 T30，断言阶段进入 `DETERIORATED`。
6. 执行复评，断言阶段进入 `REASSESSMENT`。
7. 升级到 II 级，断言阶段进入 `RE_TRIAGE`。
8. 通知医生并记录说明后，断言可进入 `FINAL_DISPOSITION`。
9. 提交后，断言最终阶段为 `COMPLETED`。
10. 断言 `stage_history` 至少包含上述关键动作。

验收方法：

执行：

```powershell
cd backend
pytest -q tests/test_triage_dynamic_mvp.py
```

接口抽查：

完整跑一遍 `TRIAGE-DYN-RLQ-001` 后查看训练记录：

- `timeline_state.current_stage` 必须为 `COMPLETED`。
- `timeline_state.stage_history` 不为空。
- `stage_history` 能看到从初诊、候诊、复评、重新分诊到完成的关键转移。

达标标准：

- 状态机不只是模块存在，而是所有动态病例关键 API 都能驱动它。
- 动态报告能回放状态阶段变化。

### P0-3 动态病例学生入口不可见

问题现象：

`TRIAGE-DYN-RLQ-001` 可以通过 external id 直接启动，但普通学生从 `/api/triage/cases` 获取病例列表时看不到该病例。原因是病例数据中：

```json
"approved_for_training": false
```

而列表接口对学生过滤未审核病例。

涉及文件：

- `backend/triage_data/cases_dynamic/TRIAGE-DYN-RLQ-001.json`
- `backend/services/triage_repository.py`
- `backend/routers/triage.py`
- `frontend/src/pages/triage/TriageCaseSelect.jsx`

建议修复方法：

有两种可选路线，建议采用路线 A。

路线 A：保留审核机制，新增一个已审核的 MVP 演示动态病例。

1. 将 `TRIAGE-DYN-RLQ-001` 复制或调整为教学验收专用病例。
2. 确认病例数据经过人工核对后，将：
   - `review_status.expert_reviewed=true`
   - `review_status.approved_for_training=true`
   - `stage` 从 `DRAFT` 调整为 `PUBLISHED` 或项目已有的发布状态。
3. 保留 `ai_generated=true` 也可以，但必须明确是教学模拟，不用于真实临床。
4. 学生列表显示至少一个 `is_dynamic=true` 的病例。

路线 B：新增开发/验收模式入口。

1. 保持病例为 draft。
2. 给教师或开发模式提供动态病例直达入口。
3. 不建议普通学生使用该路线，因为会绕过病例审核机制。

建议测试：

1. 使用 `student1/123456` 登录。
2. 请求 `/api/triage/cases`。
3. 断言列表中至少包含一个 `is_dynamic=true` 且可启动的病例。
4. 点击该病例后，前端应进入动态训练页，而不是静态训练页。

验收方法：

接口验收：

```powershell
cd backend
python - <<'PY'
from fastapi.testclient import TestClient
from main import app

with TestClient(app) as c:
    token = c.post('/api/auth/login', json={'username':'student1','password':'123456'}).json()['access_token']
    h = {'Authorization': 'Bearer ' + token}
    items = c.get('/api/triage/cases', headers=h).json()['items']
    dynamic_items = [x for x in items if x.get('is_dynamic')]
    print(dynamic_items[:3])
    assert dynamic_items, '学生病例列表中没有可见动态病例'
PY
```

人工验收：

1. 登录学生账号。
2. 进入预检分诊病例列表。
3. 能看到至少一个动态病例。
4. 点击后进入动态训练页。
5. 能推进 T0/T15/T30。

达标标准：

- 学生正常入口可见并可进入至少一个动态病例。
- 未审核草稿病例不会误入正式学生训练或考试库。

### P0-4 学员操作时间线不完整

问题现象：

当前动态流程可记录：

- `measure_vitals`
- `initial_triage`
- `advance_time`
- `reassess`
- `notify_doctor`

但仍存在不足：

1. `/save-notes` 只写 `notes`，没有写入 `student_actions`。
2. `/submit` 没有作为 `submit` 动作写入 `student_actions`。
3. 如果前端通过 `/reassess` payload 完成升级，而不调用 `/upgrade`，`student_actions` 中不会出现 `upgrade_triage`。
4. `messages` 中通常只保留初始患者开场白，T15/T30 的患者变化信息没有稳定保存为消息或系统事件。

涉及文件：

- `backend/routers/triage.py`
- `backend/services/triage_timeline.py`
- `backend/services/triage_repository.py`
- `backend/services/triage_scoring_v4.py`
- `frontend/src/pages/triage/TriageDynamicTraining.jsx`

建议修复方法：

1. 在 `/save-notes` 中调用 `record_student_action(record, "record_note", {...})`。
2. 在 `/submit` 中调用 `record_student_action(record, "submit", {...})`。
3. 在 `/reassess` 中，如果 `selected_level` 与初始分诊等级不同，或达到病例要求的最终等级，应额外记录：
   - `upgrade_triage`
   - payload 包含 `from_level`、`to_level`、`from_area`、`to_area`、`reason`、`notify_doctor`
4. 保留 `/upgrade` endpoint，但前端可以选择：
   - 方案 A：复评选择新等级后自动调用 `/upgrade`。
   - 方案 B：后端在 `/reassess` 中自动识别升级并写 `upgrade_triage`。
   - 建议使用方案 B，减少前端流程分叉。
5. 在 `/timeline/advance` 中，对触发事件稳定写入：
   - `timeline_state.system_events`
   - 必要时 `messages` 中追加患者自然表达。
6. 动态病例数据中的 timeline event 应补齐 `patient_expression`，否则前端不会追加患者消息。
7. 训练报告中统一读取：
   - `student_actions`
   - `triage_decisions`
   - `vital_measurement_log`
   - `timeline_state.system_events`
   - `notes`

建议测试：

新增测试覆盖完整动作线：

1. T0 测量生命体征。
2. 记录初始分诊和 30 分钟复评。
3. 推进 T15 并测量。
4. 推进 T30 并测量。
5. 执行复评并选择 II 级红区。
6. 通知医生。
7. 保存记录说明。
8. 提交病例。
9. 断言 `student_actions` 至少包含：
   - `measure_vitals`
   - `initial_triage`
   - `advance_time`
   - `reassess`
   - `upgrade_triage`
   - `notify_doctor`
   - `record_note`
   - `submit`
10. 断言 `vital_measurement_log` 包含 T0/T15/T30。
11. 断言报告中能看到学员操作时间线。

验收方法：

接口抽查：

完整跑一遍动态病例后，获取训练记录：

```text
GET /api/triage/training/records/{record_id}
```

检查：

- `student_actions` 包含完整动作链。
- `notes` 中有记录说明。
- `timeline_report.student_actions` 能展示完整操作。
- `timeline_report.vital_measurement_log` 显示 T0/T15/T30。

达标标准：

- 报告能回答“学生什么时候做了什么”。
- 复评、升级、通知医生、记录说明、提交都能被追踪。

## 三、P1 应尽快修复项

### P1-1 动态病例 T15/T30 患者自然表达未稳定进入对话区

问题现象：

`/timeline/advance` 只有在事件中存在 `patient_expression` 时才会追加患者消息。当前腹痛动态病例的 T15/T30 主要有 `event_description`，但缺少稳定的 `patient_expression`，导致对话区可能只显示开场白。

建议修复方法：

1. 在 `TRIAGE-DYN-RLQ-001.json` 中为 T15/T30 event 补充：
   - T15：`patient_expression="疼得更厉害了，还有点恶心，我坐不住。"`
   - T30：`patient_expression="我头晕，疼得受不了了，身上一直冒冷汗。"`
2. `/timeline/advance` 中写消息时可按优先级选择：
   - `patient_expression`
   - `student_prompt` 仅 practice 模式可用
   - `event_description` 仅作为系统事件，不建议直接作为患者原话
3. 训练报告中把患者自然表达和系统事件分开显示。

验收方法：

1. 动态病例推进到 T15。
2. 对话区出现患者加重表达。
3. 推进到 T30。
4. 对话区出现头晕、冷汗、疼痛加重表达。
5. exam 模式下不出现“建议复评”“必须升级”等指导性话术。

### P1-2 训练模式和考核模式边界需继续收紧

问题现象：

当前已有 mode 字段，但需要更明确地约束 practice/exam 的差异。尤其要避免 practice 的提示字段通过复用接口进入 exam。

建议修复方法：

1. 建立统一脱敏层，不要让各 router 分散处理。
2. 定义模式字段：
   - `practice`
   - `exam`
   - `osce`
3. 所有返回学生端的数据先经过 mode-aware serializer。
4. 只允许后端评分模块读取完整标准答案。
5. 教师端和学生端使用不同接口或不同权限字段。

验收方法：

1. 对 practice/exam/osce 各启动一次动态病例。
2. 对比 `/cases/{id}`、`/timeline`、`/current-state`、`/records/{id}`。
3. exam/osce 在提交前不得返回评分、标准答案、推荐动作、严重错误判定。

### P1-3 前端动态训练页缺少交互级测试

问题现象：

`frontend/src/__tests__/TriageDynamicTraining.test.jsx` 当前主要验证 API 函数存在、模块可导入，没有验证真实 UI 行为。

建议修复方法：

1. 使用 Testing Library mock API，渲染 `TriageDynamicTraining`。
2. 覆盖以下交互：
   - 初始加载动态病例。
   - 显示时间轴当前分钟。
   - 点击测量生命体征后显示结果。
   - 选择 III 级、黄区、30 分钟复评并记录初始分诊。
   - 点击推进时间后显示 T15/T30。
   - 点击执行复评。
   - 勾选通知医生或点击通知医生。
   - 记录说明。
   - 提交后跳转或显示提交结果。
3. 断言不会把标准答案直接显示在考核模式页面。

验收方法：

执行：

```powershell
cd frontend
npm run test -- --run
```

达标标准：

- 动态训练页至少有 3 个交互级测试。
- 不再只做“函数存在性”测试。

### P1-4 后端动态测试需要按验收标准收紧

问题现象：

现有状态机测试只断言最终阶段“不等于 ARRIVAL”，太弱；考核脱敏测试只检查 `timeline_events`，未检查 `patient_state`。

建议修复方法：

加强 `backend/tests/test_triage_dynamic_mvp.py`：

1. 新增 `test_exam_timeline_patient_state_redacted`。
2. 新增 `test_dynamic_state_machine_reaches_completed`。
3. 新增 `test_dynamic_student_action_timeline_complete`。
4. 新增 `test_student_can_see_at_least_one_dynamic_case`。
5. 新增 `test_dynamic_current_state_exam_redacted`。

验收方法：

执行：

```powershell
cd backend
pytest -q tests/test_triage_dynamic_mvp.py tests/test_triage_case_safe_redaction.py
```

达标标准：

- 测试失败时能准确暴露本留言板 P0 问题。
- 测试通过时能证明动态 MVP 验收关键项已覆盖。

## 四、P2 可排期优化项

### P2-1 静态胸痛样例与原始验收文本不完全一致

问题现象：

原始需求中要求至少保证一个静态胸痛病例：

- 男，56 岁
- 胸闷、胸痛 30 分钟
- 标准等级 II 级
- 红区或胸痛优先诊区

当前库中存在静态胸痛病例，但不是该精确样例：

- `TRIAGE-001`：58 岁男性，胸痛伴冷汗、血压下降，标准 I 级。
- `TRIAGE-006`：28 岁男性，搬重物后胸壁刺痛，标准 IV 级。

建议修复方法：

1. 如果严格按原始验收文本执行，新增或调整一个静态胸痛 II 级病例。
2. 不建议覆盖现有高危 I 级胸痛病例。
3. 可新增 `TRIAGE-STATIC-CHEST-II-001`：
   - 男，56 岁
   - 胸骨后压榨样疼痛 30 分钟
   - 左肩和左臂放射
   - 冷汗、恶心、轻度气短、高血压史
   - T 36.7，HR 108，R 22，BP 158/96，SpO2 96，NRS 8，意识清楚
   - 标准 II 级
   - 红区或胸痛优先诊区
4. 将该病例设置为 `is_dynamic=false`，并确保旧静态训练页能完成训练、评分和反馈。

验收方法：

1. 学生病例列表可见该静态胸痛病例。
2. 从静态训练页进入。
3. 能问诊、测量生命体征、选择等级和区域、提交评分。
4. 判为 II 级且红区/胸痛优先诊区时通过。
5. 判为 IV 级或普通候诊时触发严重错误或重扣分。

### P2-2 浏览器级端到端验收仍需补齐

问题现象：

本次核查完成了服务启动 smoke，但未完成完整浏览器截图式交互验收。原因是当前会话没有 Browser 插件，外部 Node 环境也未安装 Playwright 包；按当前约束不临时安装新浏览器依赖。

建议修复方法：

1. 优先引入项目级 Playwright e2e 测试，或在有 Browser 插件的环境中执行浏览器验收。
2. 覆盖：
   - 登录。
   - 进入病例列表。
   - 选择动态病例。
   - T0 测量、初始分诊。
   - 推进 T15/T30。
   - 复评、升级、通知医生、记录说明。
   - 提交并查看训练报告。
3. 捕获控制台错误和关键页面截图。

验收方法：

浏览器验收必须输出：

- 页面 URL。
- 页面标题。
- 首屏非空截图。
- 动态训练页截图。
- T30 恶化后截图。
- 训练报告截图。
- 控制台错误列表。

达标标准：

- 页面无框架错误覆盖层。
- 关键按钮可点击。
- 文本不重叠。
- 动态病例流程可从 UI 完成，而不是只靠接口。

## 五、建议实施顺序

第一批必须先做：

1. 修复 exam/osce 的 `patient_state` 脱敏。
2. 修复状态机初始化和关键 API transition。
3. 让至少一个动态病例从学生正常入口可见。
4. 补齐 `student_actions` 的 `record_note`、`submit`、`upgrade_triage`。

第二批紧随其后：

1. 补齐 T15/T30 `patient_expression`。
2. 加强后端动态 MVP 测试。
3. 加强前端动态训练页交互测试。

第三批作为完整交付：

1. 新增或确认静态 II 级胸痛病例。
2. 加入浏览器级端到端验收。
3. 补充教师端对动态病例审核发布的流程说明。

## 六、最终验收清单

完成上述修复后，按以下清单验收。

### 后端自动化验收

执行：

```powershell
cd backend
pytest -q
```

必须满足：

- 所有测试通过。
- 新增测试覆盖 exam/osce 脱敏。
- 新增测试覆盖状态机最终进入 `COMPLETED`。
- 新增测试覆盖学生可见动态病例。
- 新增测试覆盖完整学生操作时间线。

### 前端自动化验收

执行：

```powershell
cd frontend
npm run lint
npm run test -- --run
npm run build
```

必须满足：

- lint 通过。
- 单元测试通过。
- 动态训练页至少有交互级测试。
- build 通过。

### 接口手工验收

1. 学生登录后，`/api/triage/cases` 至少返回一个 `is_dynamic=true` 的病例。
2. practice 模式启动动态腹痛病例，能完成 T0/T15/T30。
3. exam 模式启动同病例，提交前不得泄露标准答案字段。
4. 正确流程提交后，报告显示：
   - 标准初始等级和学员初始等级。
   - 标准最终等级和学员最终等级。
   - 患者状态时间线。
   - 学员操作时间线。
   - 生命体征测量记录。
   - 是否按时复评。
   - 是否识别恶化。
   - 是否升级分诊。
   - 是否通知医生。
   - 是否触发严重错误。
5. 错误流程提交后，系统能识别：
   - 患者恶化后未复评。
   - 复评后未升级。
   - 候诊区危重化未通知医生。

### UI 手工验收

1. 从登录页进入病例列表。
2. 选择动态腹痛病例。
3. 页面显示患者信息区、时间轴区、操作区、动态生命体征区。
4. 点击测量生命体征后显示当前时间点结果。
5. 点击推进时间后，时间轴和患者状态更新。
6. T30 后能执行复评、升级分诊、通知医生、记录说明。
7. 提交后能进入或显示训练报告。
8. 页面无明显乱码、重叠、按钮不可点击、内容溢出。

## 七、通过标准

只有同时满足以下条件，才可将动态预检分诊平台 MVP 判定为达标：

1. 原有静态训练仍能启动、测量、提交、评分。
2. 学生正常入口至少可进入一个动态病例。
3. 动态病例包含 T0/T15/T30 三个时间节点。
4. 生命体征随时间节点变化。
5. 初始分诊和复评分诊均被记录。
6. 系统能判断是否设置复评时间。
7. 系统能判断是否按时复评。
8. T30 恶化后能要求升级到 II 级。
9. 严重错误能覆盖未复评、未升级、未通知医生。
10. 考核模式提交前不泄露标准答案。
11. 状态机能真实推进到 `COMPLETED`。
12. 训练报告含患者状态时间线和学员操作时间线。
13. 后端、前端测试和构建全部通过。
14. 页面能通过真实 UI 跑完整动态病例。

