# 开发历史与当前状态总结

> **最后更新**: 2026-06-20  
> **阅读对象**: 后续 AI 模型或开发者

## 一、开发历程

| 阶段 | 内容 |
|------|------|
| V1 | 静态训练闭环: 登录/病例/关键词问诊/观察/测量/基础评分 |
| V2-V3 | LLM 接入 + 6层对话管线 + 规则引擎 + 状态机 slot |
| V4-V5 | 动态时间线 + 复评 + 教师管理 (班级/任务/审核) |
| V6 早期 | 多患者场景/学习路径/研究导出/安全审计 骨架 |
| **MVP 验收攻坚** (2026-06-19~20) | 4 轮留言板驱动修复，详见下方 |

## 二、MVP 验收攻坚 (2026-06-19~20)

### 第1轮: AI问题留言板 (13项)
路由404/ Docker只读/ 端口统一/ lint修复/ 测试补齐/ axios统一/ 权限加固/ XSS/ 学习路径/ 死代码/ .gitignore/ 原子写入/ README

### 第2轮: 观察评分生命体征 (4问题)
对话清空/ 提交无评分/ 观察"未描述"/ 生命体征乱码 → 50病例数据清洗

### 第3轮: 预检分诊功能差距 (7项) + 固定回复 (6项)
动态训练页测量UI/ AI/语音权限/ LLM拟人化(50病例变体)/ 评测集/ 规则引擎扩展(血糖/MEWS/SI/9条严重错误)/ 班级仪表盘/ 旧留言板归档/ **对话slot数据修复(49病例226 slots)**/ V1占位过滤/ 对话多样性回归测试

### 第4轮: 动态MVP实施 (9阶段)
MVP病例(T0/T15/T30)/ 状态机(13状态)/ 时间轴扩展/ 动态生命体征/ 分诊决策分离/ 动态评分(10维度)/ 前端动态页/ 训练报告/ 模式差异 → 后端60 tests

### 第5轮: MVP核查改进 (12项P0+P1)
exam patient_state脱敏/ 状态机setdefault+全部API transition/ 病例审核过滤/ student_actions补齐(submit/notes/upgrade)/ T15/T30 patient_expression/ 模式边界收紧/ 前端交互测试/ 后端硬测试/ 静态II级胸痛病例/ E2E Playwright(3 tests)

### 第6轮: MVP验收未达标修复 (10项P0+P1+P2)
完整患者状态脱敏/ 状态机COMPLETED/ 病例学生可见/ 操作链完整/ 自然表达/ 测试收紧(5新测试)/ Playwright安装+3 E2E通过

## 三、当前系统状态

### 代码质量

| 指标 | 值 |
|------|-----|
| 后端测试 | **78 passed** (14 文件) |
| 前端 lint | 0 errors 0 warnings |
| 前端 build | 成功 |
| 前端 test | **26 passed** (4 文件) |
| E2E test | **3 passed** (Playwright) |

### 功能完成度

| 模块 | 状态 |
|------|------|
| 用户认证 (student/teacher/reviewer/admin) | ✅ |
| 静态病例训练 (17 cases) | ✅ |
| 动态病例训练 (35 cases, T0/T15/T30) | ✅ |
| 虚拟患者对话 (6层管线 + LLM) | ✅ |
| 第一眼观察 + 生命体征测量 (按时点) | ✅ |
| 自动评分 (5级链) + 规则引擎 (23规则+20阈值) | ✅ |
| 患者状态机 (13状态, 全API驱动) | ✅ |
| 动态报告 (时间线+体征日志+操作链+4标志) | ✅ |
| 安全脱敏 (4层: case/timeline/patient_state/list) | ✅ |
| 教师管理 (病例审核含结构校验/任务/班级/分析) | ✅ |
| 学习路径/队列训练/研究导出 | 🟡 骨架 |
| 语音模块 | 🟡 骨架 |
| 100并发压测 | 🟡 未执行 |

### 已知待办

1. **病例扩展**: 52→100 (V6要求)
2. **PDF/Excel 导出**: 需安装依赖 (weasyprint/openpyxl)
3. **结构化病例编辑器**: 前端+后端
4. **100并发压测**: 验证 JSON 写入 → 可能需迁移 SQLite 事务
5. **语音问诊**: 转文本→意图→回答→回放
6. **多人候诊队列**: 完整评分
7. **虚拟患者视觉**: 绑定病例字段

## 四、关键文件速查

| 需求 | 文件 |
|------|------|
| 修改对话逻辑 | `backend/services/triage_patient_dialogue.py` |
| 修改评分 | `backend/services/triage_scoring_v4.py` |
| 添加 API | `backend/routers/triage.py` |
| 修改病例 | `backend/triage_data/cases_dynamic/*.json` |
| 前端页面 | `frontend/src/pages/triage/*.jsx` |
| 前端 API | `frontend/src/api.js` |
| 病例校验 | `python backend/scripts/validate_triage_dialogue_data.py` |
| 批量迁移 | `python backend/tools/migrate_dynamic_cases.py` |

## 五、留言板索引

| 文件 | 状态 |
|------|------|
| `AI问题留言板.md` | 📦 已归档 (13项全部修复) |
| `观察评分生命体征问题留言板.md` | 📦 已归档 |
| `固定回复问题留言板.md` | 📦 已归档 |
| `预检分诊功能开发要求差距留言板.md` | 📦 已归档 |
| `动态预检分诊平台MVP实施验收留言板.md` | 📦 已归档 (9阶段完成) |
| `动态预检分诊平台MVP当前核查改进留言板.md` | 📦 已归档 (12项P0+P1完成) |
| `动态预检分诊平台MVP验收未达标修复留言板.md` | 📦 已归档 (10项P0-P2完成) |

## 六、给后续 AI/开发者的接手指南

1. **先读 00-overview.md** 了解架构，然后读本文。
2. **运行验证**: `pytest -q`(78), `npm run lint`, `npm run build`, `npm run test -- --run`(26), `npx playwright test`(3)。
3. **如需继续开发**，参考上方"已知待办"列表。
4. 修改病例数据前先跑 `validate_triage_dialogue_data.py`。
5. 所有变更后必须通过 lint + build + test + pytest。
6. **不要**因终端中文乱码批量改源码编码——用 `Path().read_text(encoding="utf-8")` 确认。
7. **权限**: 教师接口 `if role != "teacher": 403`，学生接口校验 `user_id` 归属。
8. **安全**: 所有学生端数据必须过脱敏——`get_case_safe` / `sanitize_timeline_events_for_mode` / `sanitize_patient_state_for_mode` / `list_cases(include_draft)`。

---

**系统当前可教学验收。** `http://127.0.0.1:3010`，用 `student1/123456` 登录即可体验完整动态预检分诊训练流程。
