# 快速启动指南

## 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 教师/审核员 | `admin` | `admin123` |
| 学生 | `student1` ~ `student5` | `123456` |

## 一键启动

双击 `start.bat` → 后端 :8010 + 前端 :3010

或手动：
```bash
# 后端
cd backend && pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8010

# 前端
cd frontend && npm install
npx vite --host 127.0.0.1 --port 3010
```

访问: **http://127.0.0.1:3010**

## Docker

```bash
docker compose up --build
# 前端 :8081, 后端 :8010
```

## 核心验证

```bash
cd backend && pytest -q              # 78 passed
cd frontend && npm run lint          # 0/0
npm run test -- --run                # 26 passed
npm run build                        # 成功
npx playwright test                  # 3 passed (E2E)
```

## 动态病例体验

1. 用 `student1 / 123456` 登录
2. 病例列表中找到 `右下腹痛候诊期间病情恶化`（动态标识）
3. 点击进入 → 右侧面板：
   - 第一眼观察 → 测量生命体征 → 选择 III 级/黄区 → 记录初始分诊
   - 推进时间到 T15 → 看到病情变化提示 → 推进到 T30
   - 选择 II 级/红区 → 勾选通知医生 → 执行复评
   - 记录说明 → 提交分诊 → 查看动态报告

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `SECRET_KEY` | **是** | JWT 密钥 |
| `DEEPSEEK_API_KEY` | 否 | LLM API Key |
| `TRIAGE_USE_LLM` | 否 | 启用 LLM 自然化 (默认 false) |
| `TRIAGE_STATIC_DATA_DIR` | 否 | 静态病例目录 |
| `TRIAGE_RUNTIME_DATA_DIR` | 否 | 运行时数据目录 |
