# 预检分诊训练系统

用于新入职护士预检分诊训练的网页系统。**仅用于教学训练，不用于真实临床分诊。**

## 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 教师 | `admin` | `admin123` |
| 学生 | `student1` ~ `student5` | `123456` |

## 本地启动

### 方式一：一键启动

双击 `start.bat`，自动启动后端（8010端口）和前端（3010端口）。

### 方式二：手动启动

```bash
# 后端
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8010

# 前端
cd frontend
npm install
npx vite --host 127.0.0.1 --port 3010
```

访问：**http://localhost:3010**

## Docker 启动

```bash
docker compose up --build
```

- 后端：http://localhost:8010
- 前端：http://localhost:8081

## 环境变量

复制 `.env.example` 为 `.env`，主要配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | JWT 密钥（必填） | — |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | — |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-chat` |
| `TRIAGE_USE_LLM` | 启用 LLM 驱动患者对话 | `false` |
| `DATABASE_URL` | 数据库连接 | `sqlite:///./data.db` |
| `CORS_ORIGINS` | 允许跨域来源 | `http://localhost:3010,...` |
| `TRIAGE_STATIC_DATA_DIR` | 静态病例数据目录（Docker 中只读） | `backend/triage_data` |
| `TRIAGE_RUNTIME_DATA_DIR` | 运行时数据目录（Docker 中可写） | `backend/triage_data` |

## 数据目录

- `backend/triage_data/cases/` — 静态病例库（只读）
- `backend/triage_data/rubrics/` — 评分标准
- `backend/triage_data/rules/` — 分诊规则
- `backend/triage_data/records/` — 训练记录（运行时写入）
- 运行时数据文件（`cohorts.json`, `tasks.json`, `learning_paths.json` 等）在 `TRIAGE_RUNTIME_DATA_DIR` 下

## 验证命令

```bash
# 后端
cd backend
pytest -q                           # 运行测试

# 前端
cd frontend
npm run lint                        # 代码检查
npm run build                       # 生产构建
npm run test                        # 运行测试 (26 passed)
npx playwright test                 # E2E 测试 (3 passed)
```

## 当前状态

| 指标 | 数值 |
|------|------|
| 后端测试 | **78 passed** |
| 前端测试 | **26 passed** |
| E2E 测试 | **3 passed** |
| 病例总数 | 52 (17 静态 + 35 动态) |
| 动态病例 | 35 (全部含 patient_states ≥3) |

## 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI (Python) |
| 数据库 | SQLite (WAL模式) + JSON 文件 |
| 认证 | JWT + bcrypt (4角色) |
| AI 引擎 | DeepSeek API |
| 前端 | React 19 + Vite 8 + React Router 7 |
| 图表 | Recharts |
| 测试 | pytest + Vitest + Testing Library + Playwright |

## 安全声明

- 本系统仅用于护理教学训练
- 不可用于真实临床分诊决策
- Docker 部署时静态病例数据挂载为只读
- 运行时数据使用独立的可写卷
- HTML 报告已做 XSS 防护

## 架构说明

完整技术文档详见 `docs/` 目录：

| 文档 | 内容 |
|------|------|
| [docs/00-overview.md](docs/00-overview.md) | 系统概述与架构 |
| [docs/01-quickstart.md](docs/01-quickstart.md) | 快速启动指南 |
| [docs/02-backend.md](docs/02-backend.md) | 后端架构与 API |
| [docs/03-frontend.md](docs/03-frontend.md) | 前端架构与组件 |
| [docs/04-data-model.md](docs/04-data-model.md) | 数据模型与规则 |
| [docs/05-deployment.md](docs/05-deployment.md) | 部署与配置 |
| [docs/06-dev-log.md](docs/06-dev-log.md) | 开发历史与当前状态总结 |

已知问题与修复记录详见 `留言板/` 目录。
