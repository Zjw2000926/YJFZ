# 预检分诊系统 AI 问题留言板

> **状态：📦 历史问题记录（已归档）**  
> 更新日期：2026-06-19（原始）/ 2026-06-19（归档）  
> 用途：给后续接手的 AI 或开发者提供可复现的问题清单、修复路径和验证方法。
> 
> **⚠️ 注意：本文件所列问题已于 2026-06-19 全部修复完毕（P0-01 ~ P2-04）。当前系统最新状态请参考 `预检分诊功能开发要求差距留言板.md`。**

## 当前审查结论（原始）

系统已具备可演示的核心训练链路：登录、病例列表、开始训练、观察、测量、提交评分均可通过接口跑通。后端测试通过，前端生产构建通过。

> **修复后状态（2026-06-19）：** 13 项问题全部修复。后端 38 tests passed，前端 lint 0/0，build 成功，test 17 passed。
> 端口统一为 3010/8010，Docker 静态/运行时数据分离，HTML escaping 完成，权限加固完成，JSON 原子写入完成。

## 本次已执行验证

在项目根目录 `D:\大语言模型调用编程\编程\新版\YJFZ` 下验证：

- `backend`: `python -m py_compile main.py routers\triage.py routers\auth.py services\triage_repository.py services\triage_admin_repository.py services\triage_v6_services.py` 通过。
- `backend`: `pytest -q` 通过，结果为 `24 passed, 1 warning`。
- `frontend`: `npm.cmd run build` 通过。
- `frontend`: `npm.cmd run lint` 失败，当前有 6 个 errors 和 6 个 warnings。
- `frontend`: `npm.cmd run test` 失败，原因是没有任何 `*.test` 或 `*.spec` 文件。
- 接口冒烟：学生账号 `student1/123456` 的登录、病例列表、训练开始、观察、测量、提交评分均返回 200。
- 教师端关键接口：`GET /api/triage/training/records/all` 当前返回 404。

注意：PowerShell 输出中文时可能出现乱码，但用 Python 按 UTF-8 读取源码可确认源文件中文正常，不要把终端显示乱码当作源码损坏。

## 建议处理顺序

1. 先修复 P0-01 教师全部训练记录接口 404。
2. 再修复 P0-02 Docker 部署时 `triage_data` 只读导致运行时写入失败。
3. 然后修复 P1-01 本地启动端口与 Vite 代理不一致。
4. 之后处理 lint、测试覆盖、权限边界和导出安全。

---

## P0-01 教师端全部训练记录接口 404

状态：待修复  
影响：教师后台“训练记录”和“导出”依赖该接口，当前会拿不到全部训练记录。

### 证据

- 前端调用位置：`frontend/src/pages/triage/TriageAdmin.jsx`
  - 第 41 行：`api.get("/training/records/all")`
  - 第 52 行：刷新记录也调用同一路径
- 后端路由注册顺序：`backend/routers/triage.py`
  - 第 128 行先注册 `@router.get("/training/records/{record_id}")`
  - 第 573 行才注册 `@router.get("/training/records/all")`
- FastAPI 路由会先匹配动态路径，导致 `all` 被当成 `record_id`。
- 已验证：教师登录后请求 `GET /api/triage/training/records/all` 返回 404。

### 修复步骤

1. 打开 `backend/routers/triage.py`。
2. 将 `get_all_records` 的路由定义整体移动到 `get_record_detail` 之前。
3. 保持教师权限判断不变：
   - 非教师返回 403。
   - 教师返回 `list_records(user_id=None)`。
4. 新增或扩展后端测试：
   - 使用教师 token 请求 `/api/triage/training/records/all` 应返回 200。
   - 使用学生 token 请求同一路径应返回 403。
   - 请求 `/api/triage/training/records/{real_record_id}` 仍能按原逻辑工作。
5. 如果不想移动代码，也可以把动态路由改为更具体路径，例如 `/training/records/detail/{record_id}`，但这会影响前端已有调用，不推荐。

### 验证命令

```powershell
cd backend
pytest -q
python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); c.__enter__(); t=c.post('/api/auth/login', json={'username':'admin','password':'admin123'}).json()['access_token']; h={'Authorization':'Bearer '+t}; print(c.get('/api/triage/training/records/all', headers=h).status_code); c.__exit__(None,None,None)"
```

期望最后输出 `200`。

---

## P0-02 Docker 部署会阻塞运行时 JSON 写入

状态：待修复  
影响：Docker 环境中训练记录、任务、班级、病例审核、学习路径、AI 事件等功能可能写入失败。

### 证据

- `docker-compose.yml` 第 10 行将 `./backend/triage_data` 挂载到 `/app/triage_data:ro`。
- 后端运行时会写入 `triage_data`：
  - `backend/services/triage_repository.py` 写入 `triage_data/records/*.json`。
  - `backend/services/triage_admin_repository.py` 写入 `cohorts.json`、`tasks.json`、`case_reviews.json`、`case_versions.json`。
  - `backend/services/triage_v6_services.py` 写入 `learning_paths.json`、`ai_events.json`、`safety_audits.json`、`voice_events.json`、`organizations.json`、`case_library_scopes.json`、`scenarios/queue_records.json` 等。
- 当前 compose 只给 SQLite 数据库挂了可写卷 `/app/data`，没有给这些 JSON 运行时数据可写卷。

### 推荐修复方案

优先做“静态病例数据只读，运行时数据可写”的拆分。

1. 新增配置项，例如：
   - `TRIAGE_STATIC_DATA_DIR`
   - `TRIAGE_RUNTIME_DATA_DIR`
2. 修改 `triage_repository.py`：
   - 病例、规则、rubric、mapping、intent 从静态目录读取。
   - records 从运行时目录读取和写入。
3. 修改 `triage_admin_repository.py` 和 `triage_v6_services.py`：
   - 任务、班级、审核、学习路径、AI 事件、队列记录等全部写入运行时目录。
4. 修改 `docker-compose.yml`：
   - 保留病例库只读挂载，例如 `./backend/triage_data/cases:/app/static_triage_data/cases:ro`。
   - 增加运行时可写卷，例如 `yjfz_runtime_data:/app/runtime_triage_data`。
   - 设置环境变量指向这两个目录。
5. 确保本地开发不需要额外配置时仍默认使用 `backend/triage_data`。

### 快速临时方案

如果短期只是演示，可以先去掉 `:ro`。但这会让容器直接改宿主病例数据目录，不适合作为最终方案。

### 验证方法

1. `docker compose up --build`。
2. 用学生账号开始并提交一次训练。
3. 用教师账号创建一个班级和任务。
4. 检查容器日志没有 `Permission denied` 或只读文件系统错误。
5. 重启容器后确认训练记录、任务和班级仍存在。

---

## P1-01 本地启动脚本与 Vite 代理/CORS 配置不一致

状态：待修复  
影响：使用 `start.bat` 启动时，前端开发服务器可能无法代理到后端 API。

### 证据

- `start.bat`：
  - 后端启动在 `127.0.0.1:8010`。
  - 前端启动在 `127.0.0.1:3010`。
- `frontend/vite.config.js`：
  - dev server 默认端口是 `3000`。
  - `/api` proxy 目标是 `http://127.0.0.1:8000`。
- `.env` 和 `.env.example` 当前 CORS 主要包含 `3000`、`8000`，没有覆盖 `3010`、`8010`。

### 修复步骤

选择一种端口策略并全项目统一。

推荐策略 A：沿用 `start.bat` 的 3010/8010。

1. 修改 `frontend/vite.config.js`：
   - `server.port` 改为 `3010`。
   - proxy target 改为 `http://127.0.0.1:8010`。
2. 修改 `.env.example`：
   - `CORS_ORIGINS=http://localhost:3010,http://127.0.0.1:3010,http://localhost:8010,http://127.0.0.1:8010`
3. 同步修改当前 `.env`，但注意不要泄露真实密钥。
4. 检查 `start.bat` 中路径是否仍适配当前项目目录。

备选策略 B：统一回 3000/8000。

1. 修改 `start.bat` 让后端使用 8000，前端使用 3000。
2. 保持 Vite 和 CORS 不变。

### 验证方法

1. 运行 `start.bat`。
2. 打开 `http://localhost:3010` 或统一后的前端端口。
3. 登录 `student1/123456`。
4. 打开浏览器网络面板，确认 `/api/auth/login` 和 `/api/triage/cases` 返回 200。

---

## P1-02 前端 lint 当前失败

状态：待修复  
影响：代码质量门禁不能通过，CI 一旦开启 lint 会失败。

### 证据

运行 `cd frontend && npm.cmd run lint` 得到 12 个问题，其中 6 个 errors：

- `frontend/src/components/Layout.jsx`
  - `BarChart3` 未使用。
  - `FileText` 未使用。
- `frontend/src/components/Toast.jsx`
  - `react-refresh/only-export-components`，文件同时导出组件和 hook。
- `frontend/src/components/ui/ConfirmDialog.jsx`
  - 同样触发 `react-refresh/only-export-components`。
- `frontend/src/pages/triage/TriageRecordDetail.jsx`
  - `correctItems` 未使用。
- `frontend/src/pages/triage/TriageTraining.jsx`
  - `measuredResults` 未使用。

同时还有 hook dependency 和无效 eslint-disable warnings。

### 修复步骤

1. 删除未使用 import：
   - `Layout.jsx` 删除 `BarChart3`、`FileText`。
2. 删除或使用未使用变量：
   - `TriageRecordDetail.jsx` 删除 `correctItems`，或把它用于渲染正确项。
   - `TriageTraining.jsx` 如果不展示 `measuredResults`，删除 state；如果要展示测量结果，将其接入 UI。
3. 处理 Fast Refresh 规则：
   - 将 `useToast` 移到单独文件，例如 `frontend/src/components/useToast.js`。
   - 将 `useConfirm` 移到单独文件，例如 `frontend/src/components/ui/useConfirm.js`。
   - 保持 provider 组件文件只导出组件。
4. 处理 hook dependency warnings：
   - 能稳定依赖的补到依赖数组。
   - 对于 `searchParams` 这类对象，先派生稳定值，例如 `const caseId = searchParams.get("case")`，再依赖派生值。
5. 删除无效的 `eslint-disable`。

### 验证命令

```powershell
cd frontend
npm.cmd run lint
npm.cmd run build
```

期望 lint 和 build 都通过。

---

## P1-03 前端测试脚本没有测试文件

状态：待补齐  
影响：`npm.cmd run test` 会失败，且当前没有前端回归保护。

### 证据

运行 `cd frontend && npm.cmd run test` 输出：

```text
No test files found, exiting with code 1
include: **/*.{test,spec}.?(c|m)[jt]s?(x)
```

### 修复步骤

1. 先补 3 类最小测试：
   - `src/api.test.js`：验证 Authorization header 注入、401 清理本地 token。
   - `src/App.test.jsx`：无 token 时访问 `/triage` 跳转 `/login`。
   - 训练页面或病例选择页 smoke test：mock API，验证页面能渲染病例列表。
2. 如果短期不想写测试，至少在 `vitest.config.js` 或 package script 中明确 `--passWithNoTests`。但这只是让门禁不报错，不推荐作为最终方案。
3. 为每个后续修复补对应回归测试：
   - P0-01 对应后端测试。
   - P1-02 对应 lint。
   - P2-01 对应 HTML escaping 测试。

### 验证命令

```powershell
cd frontend
npm.cmd run test
```

期望测试存在并通过。

---

## P1-04 前端存在多个自建 axios 客户端，错误处理不一致

状态：待统一  
影响：教师端、任务页、学习路径页绕过了 `src/api.js` 的 401 处理和 5xx 重试逻辑，登录过期时行为不一致。

### 证据

- `frontend/src/api.js` 定义了统一 axios 实例，包含 Authorization 注入、401 清理 token、网络错误重试。
- 但以下文件自行 `axios.create({ baseURL: "/api/triage" })`：
  - `frontend/src/pages/triage/TriageAdmin.jsx`
  - `frontend/src/pages/triage/TriageTasks.jsx`
  - `frontend/src/pages/triage/TriageLearningPath.jsx`
- 自建实例只添加 Authorization header，没有统一 response interceptor。

### 修复步骤

1. 在 `frontend/src/api.js` 中新增 triage helper 函数：
   - `getTriageStatsOverview`
   - `getAllTriageRecords`
   - `getTriageTasks`
   - `createTriageTask`
   - `deleteTriageTask`
   - `getTriageCohorts`
   - `createTriageCohort`
   - `getTriageLearningPath`
   - `getTriageScenarios`
2. 或者导出一个 `triageApi`，但仍要复用同一套 request/response interceptors。
3. 修改三个页面移除本地 axios 实例。
4. 保持路径前缀清楚：统一客户端 `baseURL: "/api"` 时，helper 内路径写 `/triage/...`。
5. 增加前端测试验证 401 时会回登录页。

### 验证方法

1. 手动把 localStorage 中 token 改成无效值。
2. 访问教师后台或学习路径页。
3. 期望被清理登录状态并跳转 `/login`。

---

## P1-05 部分统计、AI 日志和组织接口对学生开放，权限边界需确认

状态：待产品确认并修复  
影响：学生账号能读取全局统计、错误类型、AI 事件、组织列表；这可能暴露其他学员训练趋势或系统内部 AI 日志。

### 证据

学生账号 `student1/123456` 当前请求结果：

- `GET /api/triage/stats/overview` 返回 200。
- `GET /api/triage/stats/error-types` 返回 200。
- `GET /api/triage/ai-events` 返回 200。
- `GET /api/triage/organizations` 返回 200。
- `GET /api/triage/research/export` 返回 403。
- `GET /api/triage/safety/audits` 返回 403。

后端代码位置：

- `backend/routers/triage.py` 的 `stats_overview`、`stats_error_types`、`get_ai_events`、`get_orgs` 没有教师角色限制。
- `backend/services/triage_stats.py` 的 `get_overview()` 读取全部训练记录。

### 修复步骤

1. 和产品确认学生是否允许看全局看板。
2. 如果不允许：
   - `stats/overview`、`stats/error-types`、`ai-events`、`organizations` 增加教师权限限制。
   - 学生只允许访问自己的 `stats/students/{user_id}` 和自己的学习路径。
3. 如果允许学生看部分概览：
   - 新增学生专用接口，只聚合当前用户数据。
   - 教师接口继续返回全局数据。
4. AI 事件默认应限制教师或管理员查看；如果学生需要查看，应只能按自己的 record_id 查。
5. 增加权限测试：
   - 学生访问全局统计应 403。
   - 教师访问全局统计应 200。
   - 学生访问本人统计应 200。

### 验证命令

```powershell
cd backend
pytest -q
```

并用 TestClient 分别模拟教师和学生 token 验证状态码。

---

## P1-06 HTML 报告导出未做 HTML escaping

状态：待修复  
影响：训练对话、时间线表现、评分项目等内容直接拼进 HTML，可能造成报告页 XSS 或破坏页面结构。

### 证据

`backend/services/triage_admin_repository.py` 的 `build_html_report(record)`：

- 第 112 行直接拼接评分维度 key。
- 第 117 行直接拼接 `patient_expression`。
- 第 126 行直接拼接 `m.get("content")`。

这些字段可能包含用户输入或 AI 输出，不能直接进入 HTML。

### 修复步骤

1. 在 `build_html_report` 中引入标准库：

```python
from html import escape
```

2. 对所有动态内容调用 `escape(str(value))`：
   - `score`、`ps`、`level`、`zone`
   - 评分维度名称
   - 时间线表现
   - message role 和 content
3. URL 或属性值如果后续加入，也必须 escape。
4. 新增测试：
   - 构造 `record["messages"] = [{"role":"student","content":"<script>alert(1)</script>"}]`
   - 调用 `build_html_report`
   - 断言输出不包含原始 `<script>`，而包含 `&lt;script&gt;`。

### 验证命令

```powershell
cd backend
pytest -q
```

---

## P1-07 学习路径 GET 接口会产生写入副作用

状态：待评估  
影响：`GET /api/triage/learning-path/{user_id}` 在没有 active path 时会生成新学习路径并写入文件。GET 请求不幂等，容易让测试、预取、刷新造成数据变化。

### 证据

`backend/routers/triage.py`：

- `get_user_learning_path` 先 `get_learning_path(user_id)`。
- 如果没有 path，则调用 `generate_learning_path(user_id, profile)`。
- `generate_learning_path` 会写入 `learning_paths.json`。

### 修复步骤

推荐改为读写分离：

1. `GET /learning-path/{user_id}` 只读取已有 path。
2. 新增 `POST /learning-path/{user_id}/generate` 显式生成或刷新路径。
3. 前端学习路径页：
   - GET 无数据时显示“暂无路径”。
   - 教师或学生点击“生成学习路径”后调用 POST。
4. 加测试：
   - GET 不应创建文件或新增记录。
   - POST 才创建记录。

### 临时方案

如果要保留当前自动生成体验，请在接口注释和前端命名里明确这是“读取或生成”，并避免测试中调用真实数据文件。

---

## P2-01 `register` 和 `getMe` 前端 API 函数没有后端对应路由

状态：待清理  
影响：误导后续开发者，以为系统支持注册和获取当前用户。

### 证据

- `frontend/src/api.js`：
  - `register(data)` 调用 `/auth/register`。
  - `getMe()` 调用 `/auth/me`。
- `backend/routers/auth.py` 当前只注册 `/api/auth/login`。

### 修复步骤

二选一：

1. 如果系统不开放注册：
   - 删除 `register` 和 `getMe`。
   - 前端如需要当前用户，从 localStorage 或新增 `/auth/me` 中取。
2. 如果需要 `/auth/me`：
   - 后端新增 `GET /api/auth/me`，返回当前用户 id、role、display_name、student_id。
   - 增加测试：无 token 401，有 token 200。
3. 如果需要注册：
   - 明确仅教师可创建学生账号，避免开放匿名注册。
   - 后端新增教师权限保护的用户创建接口。

---

## P2-02 运行时数据和静态病例数据混在源码目录

状态：待治理  
影响：训练记录、AI 事件、学习路径、SQLite WAL/SHM、日志混在项目目录，后续版本控制和部署迁移容易出错。

### 证据

当前目录存在：

- `backend/yjfz.db`
- `backend/yjfz.db-wal`
- `backend/yjfz.db-shm`
- `backend/triage_data/records/*.json`，当前 127 条。
- `backend/triage_data/ai_events.json`
- `backend/triage_data/learning_paths.json`
- `logs/audit.log`

项目根目录当前不是 Git 仓库，但如果后续纳入版本控制，这些运行时文件很容易被误提交。

### 修复步骤

1. 新增 `.gitignore`：
   - `backend/*.db`
   - `backend/*.db-wal`
   - `backend/*.db-shm`
   - `backend/triage_data/records/*.json`
   - `backend/triage_data/*_events.json`
   - `backend/triage_data/learning_paths.json`
   - `logs/*.log`
   - `frontend/dist`
   - `frontend/node_modules`
   - `__pycache__`
2. 把演示种子数据和运行时数据分开：
   - `backend/triage_data/seed_records` 可选保留示例。
   - 运行时记录写到 `runtime/triage_data/records` 或 Docker volume。
3. 更新 README 或启动文档说明数据目录。

---

## P2-03 JSON 文件写入没有并发保护

状态：待评估  
影响：多学生同时训练、教师同时创建任务时，JSON 文件可能出现最后写覆盖或部分写入损坏。

### 证据

- `triage_repository._save_record` 直接 `open(path, "w")`。
- `triage_admin_repository._save` 直接写整个 list JSON。
- `triage_v6_services._save` 直接写整个 list JSON。

### 修复步骤

短期：

1. 使用临时文件 + 原子替换：
   - 写入 `file.tmp`。
   - `os.replace(tmp, target)`。
2. 对 list 型文件增加文件锁。
   - Windows 可考虑 `portalocker`，但要新增依赖。
   - 不想新增依赖时，可用 SQLite 替代。

长期：

1. 将 records、tasks、cohorts、reviews、learning_paths、ai_events 等迁移到 SQLite。
2. 使用 SQLAlchemy models 和事务。
3. 保留病例库 JSON 作为只读静态数据。

### 验证方法

写一个并发测试，同时发起多个训练记录创建和任务创建请求，确认没有 JSONDecodeError、记录数正确且文件可解析。

---

## P2-04 缺少项目级 README / 运维说明

状态：待补充  
影响：其他 AI 或开发者需要从源码反推账号、端口、环境变量、验证命令，接手成本高。

### 建议 README 内容

1. 系统目标：预检分诊训练系统，非真实临床用途。
2. 默认账号：
   - 教师：`admin/admin123`
   - 学生：`student1/123456`
3. 本地启动：
   - 后端端口。
   - 前端端口。
   - 依赖安装方式。
4. Docker 启动。
5. 常用验证命令：
   - 后端测试。
   - 前端 build/lint/test。
6. 数据目录说明：
   - 静态病例库。
   - 运行时训练记录。
7. LLM 配置：
   - `DEEPSEEK_API_KEY`
   - `TRIAGE_USE_LLM`
8. 安全声明：
   - 仅教学训练，不用于真实临床分诊。

---

## 后续 AI 接手工作方式建议

1. 不要先大改架构。先修 P0-01 和 P0-02，这两个最影响系统可用性。
2. 每修一个问题，至少跑对应验证命令；涉及前端时跑 `npm.cmd run build` 和 `npm.cmd run lint`。
3. 不要把 `backend/triage_data/records` 当作测试临时目录写入。需要冒烟测试时，用 TestClient 临时替换 `services.triage_repository.RECORDS_DIR`。
4. 不要因为终端中文乱码就批量改源码编码。用 Python `Path(...).read_text(encoding="utf-8")` 或 `unicode_escape` 先确认。
5. 修 Docker 数据目录时，优先保持病例库只读，运行时数据可写。
6. 修权限问题时，先定清楚教师、学生分别能看什么数据，再写测试锁住边界。

