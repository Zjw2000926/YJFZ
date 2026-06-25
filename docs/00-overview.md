# 预检分诊训练系统 — 系统概述

> **最后更新**: 2026-06-20  
> **版本**: 动态 MVP 验收版  
> **定位**: 用于新入职护士预检分诊训练的网页教学系统。**仅用于教学训练，不用于真实临床分诊。**

## 1. 当前状态摘要

系统已通过 4 轮留言板驱动的质量攻坚，达到动态预检分诊平台 MVP 验收标准：
- 后端 78 tests passed，前端 26 tests passed + 3 E2E passed
- 52 病例（17 静态 + 35 动态），全部含 ≥3 个 patient_states
- 状态机 13 状态驱动全流程，动态生命体征按时点变化
- 考核模式完整脱敏，学生入口病例审核过滤
- 动态报告含完整时间线和学员操作链

## 2. 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI 0.115.6, Python 3.14, Uvicorn |
| 数据库 | SQLite (WAL) + JSON 文件 |
| 认证 | JWT (HS256) + bcrypt |
| AI | DeepSeek API (deepseek-chat) |
| 前端 | React 19.2, Vite 8, React Router 7 |
| 图表 | Recharts 3.8 |
| 后端测试 | pytest 8.3 (78 tests) |
| 前端测试 | Vitest 4.1 (26 tests) + Playwright (3 E2E) |

## 3. 项目规模

| 指标 | 数值 |
|------|------|
| 总病例 | 52 (17 静态 + 35 动态) |
| 分诊规则 | 23 条 |
| 生命体征阈值 | 20 条 (SpO₂/BP/HR/RR/Temp/Pain/GCS/Glucose/SI/MEWS) |
| 后端测试 | **78 passed** |
| 前端测试 | **26 passed** |
| E2E 测试 | **3 passed** |
| API 路由 | 69 个端点 |

## 4. 核心功能模块

```
预检分诊训练系统
├── 用户认证 (JWT: student / teacher / reviewer / admin)
├── 病例训练 (52 病例, practice / exam / osce 模式)
│   ├── 静态 (17): 标准问诊 → 分诊
│   └── 动态 (35): T0初评 → 等候 → T15/T30复评 → 升级
├── 虚拟患者对话 (6层管线 + DeepSeek LLM, slot质量评分)
├── 临床操作 (第一眼观察 + 生命体征测量, 按时点返回)
├── 自动评分 (动态Rubric > 真实Rubric > V4 > V3 > V1)
├── 规则引擎 (23规则 + 阈值/症状/特殊人群/严重错误/ESI)
├── 患者状态机 (13状态: ARRIVAL→...→COMPLETED)
├── 教师管理 (病例审核/任务/班级/分析/导出)
├── 教学管理 (任务/学习路径/考试模式)
└── 平台化 (队列/研究导出/安全审计/AI事件/语音事件)
```

## 5. 关键架构决策

- **数据存储**: 病例/规则为静态 JSON，运行时记录为 JSON（tmp+os.replace 原子写入），用户/消息为 SQLite
- **Docker**: 静态病例只读挂载，运行时数据独立可写卷
- **评分优先级**: `dynamic_scoring_rubric` > `scoring_rubric` > `dynamic_timeline` > `dialogue_state_machine` > V1
- **安全脱敏**: get_case_safe 移除标准答案，exam/osce 模式 timeline/patient_state 二次脱敏
- **状态机**: 13 状态 + setdefault 补齐，所有关键 API 驱动 transition

## 6. 文档索引

| 文档 | 内容 |
|------|------|
| [00-overview.md](00-overview.md) | 系统概述 |
| [01-quickstart.md](01-quickstart.md) | 快速启动 |
| [02-backend.md](02-backend.md) | 后端架构 |
| [03-frontend.md](03-frontend.md) | 前端架构 |
| [04-data-model.md](04-data-model.md) | 数据模型 |
| [05-deployment.md](05-deployment.md) | 部署配置 |
| [06-dev-log.md](06-dev-log.md) | 开发历史与当前状态 |
