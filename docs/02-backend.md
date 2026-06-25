# 后端架构

## 目录结构

```
backend/
├── main.py                     # FastAPI 入口, CORS, 种子用户
├── config.py                   # 环境变量 (DeepSeek/DB/JWT/数据目录)
├── database.py                 # SQLAlchemy 引擎
├── models.py                   # 15 ORM 表
├── schemas.py                  # Pydantic (ConfigDict 迁移完成)
├── auth.py                     # JWT + bcrypt
├── routers/
│   ├── auth.py                 # /api/auth/login
│   └── triage.py               # /api/triage/* (69 路由)
├── services/
│   ├── triage_repository.py    # 病例/记录 CRUD + 安全脱敏 + 审核过滤
│   ├── triage_patient_dialogue.py  # 6层对话管线 + slot质量评分
│   ├── triage_patient_v1.py    # V1 关键词 + 生命体征格式化
│   ├── triage_intent.py        # 意图识别 (36种)
│   ├── triage_llm_patient.py   # LLM 控制器
│   ├── triage_guard.py         # 安全护栏 (答案泄露检测)
│   ├── triage_state_machine.py # 患者状态机 (13状态, setdefault)
│   ├── triage_timeline.py      # 时间轴 (patient_states, 脱敏, 决策记录)
│   ├── triage_reassessment.py  # 复评管理 (reassessment_on_time)
│   ├── triage_scoring_v1~v6.py # V1-V6 评分引擎
│   ├── triage_scoring_real_rubric.py
│   ├── triage_scoring_v4.py    # 动态评分 (10维度, 严重错误, 时间线报告)
│   ├── triage_stats.py         # 统计看板
│   ├── triage_admin_repository.py  # 班级/任务/审核/HTML报告
│   ├── triage_v6_services.py   # 场景/学习路径/审计/AI事件
│   ├── analytics_service.py    # 班级分析
│   ├── export_service.py       # CSV 导出
│   ├── case_validator.py       # 病例结构校验
│   └── triage_rules/           # 规则引擎 (vital/symptom/special_population/severity)
├── prompts/                    # LLM 系统提示词
├── tests/                      # 14 测试文件 (78 tests)
├── tools/                      # 运维脚本
│   ├── gen_patient_variants.py
│   ├── fix_dialogue_data.py
│   ├── migrate_dynamic_cases.py
│   └── eval_intents.py
├── scripts/
│   └── validate_triage_dialogue_data.py
└── triage_data/                # 52 病例 + 规则 + 记录
```

## 关键 API (69 端点)

### 训练核心
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/cases` | 病例列表 (学生过滤未审核) |
| GET | `/cases/{id}` | 病例详情 (安全脱敏版) |
| POST | `/training/start` | 开始训练 (含状态机初始化) |
| POST | `/{id}/message` | 发送消息 (6层管线) |
| POST | `/{id}/observe` | 第一眼观察 |
| POST | `/{id}/measure` | 测量生命体征 (按时点返回) |
| POST | `/{id}/submit` | 提交分诊 + 自动评分 |

### 动态训练 (V4)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/{id}/timeline` | 时间线 (exam脱敏) |
| POST | `/{id}/timeline/advance` | 推进时间 (状态机驱动) |
| POST | `/{id}/reassess` | 复评 (升级检测) |
| POST | `/{id}/upgrade` | 升级分诊 |
| POST | `/{id}/initial-decision` | 记录初始分诊 |
| POST | `/{id}/notify-doctor` | 通知医生 |
| POST | `/{id}/save-notes` | 记录说明 |
| GET | `/{id}/current-state` | 当前患者状态 (脱敏) |

### 教师管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/cohorts` | 班级管理 |
| GET/POST | `/tasks` | 任务管理 |
| POST | `/cases/{id}/review` | 病例审核 (含结构校验) |
| GET | `/stats/overview` | 全局统计 |
| GET | `/stats/class-dashboard/{id}` | 班级仪表盘 |

## 对话服务 6 层管线

```
学生消息 → triage_patient_dialogue.py
第1层: 操作检测 (测/量/检查)
第2层: Slot 精准匹配 → _select_best_slot (质量评分)
       → LLM 自然化 或 规则合成 (_combine_slot_facts 去重)
第3层: Slot label 模糊匹配
第4层: V1 fallback (占位文本过滤)
第5层: LLM 语义兜底
第6层: 角色化"不知道"
```

## 安全脱敏层次

1. `get_case_safe`: 移除 standard_answer/scoring_rubric/patient_states 敏感字段
2. `sanitize_timeline_events_for_mode`: exam 移除提示/标准等级
3. `sanitize_patient_state_for_mode`: exam 移除 standard_triage_level/area/recommended_actions
4. `list_cases(include_draft)`: 学生只看已审核病例

## 后端测试 (78 tests, 14 文件)

| 文件 | 测试数 | 内容 |
|------|--------|------|
| test_triage_dynamic_mvp.py | ~14 | 动态 MVP: schema/timeline/vitals/reassess/upgrade/state-machine/exam-leak/student-visible/action-timeline |
| test_triage_rules.py | ~10 | 规则引擎 10 场景 |
| test_triage_scoring_v3.py | ~10 | V3 评分 |
| test_triage_case_safe_redaction.py | ~5 | 安全脱敏 (含动态) |
| test_triage_dialogue_reply_diversity.py | 3 | 对话多样性 |
| test_triage_observe.py | 4 | 观察端点 |
| test_triage_routes.py | 4 | 路由顺序 |
| test_html_escape.py | 3 | XSS 防护 |
| test_triage_controlled_llm_patient.py | ~4 | LLM 受控 |
| test_triage_concurrency.py | 2 | 并发写入 |
| 其他 | ~19 | — |
