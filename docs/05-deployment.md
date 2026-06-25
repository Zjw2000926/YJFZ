# 部署与配置

## 端口

| 环境 | 后端 | 前端 |
|------|------|------|
| 本地 | `8010` | `3010` |
| Docker | `8010` (映射 8000) | `8081` (映射 80) |

## Docker 数据分离

```yaml
volumes:
  - yjfz_db_data:/app/data                    # SQLite 可写
  - yjfz_runtime_data:/app/runtime_triage_data # JSON 可写
  - ./backend/triage_data/cases:/app/static_triage_data/cases:ro  # 只读
  - ./backend/triage_data/rules:/app/static_triage_data/rules:ro
  # ...
environment:
  - TRIAGE_STATIC_DATA_DIR=/app/static_triage_data
  - TRIAGE_RUNTIME_DATA_DIR=/app/runtime_triage_data
```

## 环境变量全集

```bash
# 安全
SECRET_KEY=                    # 必填
CORS_ORIGINS=http://localhost:3010,http://127.0.0.1:3010,http://localhost:8010

# 数据库
DATABASE_URL=sqlite:///./yjfz.db

# 数据目录
TRIAGE_STATIC_DATA_DIR=./triage_data
TRIAGE_RUNTIME_DATA_DIR=./triage_data

# DeepSeek
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
TRIAGE_USE_LLM=false

# LLM 参数
LLM_CHAT_TIMEOUT=20
LLM_CHAT_MAX_TOKENS=120
LLM_SCORING_TIMEOUT=120
LLM_SCORING_MAX_TOKENS=2048
LLM_CONCURRENT_LIMIT=10

# JWT
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

## 数据安全

- **原子写入**: `tmp + os.replace` 防并发损坏
- **HTML escaping**: `build_html_report` 全量 `html.escape()`
- **权限分层**: teacher/reviewer/admin/student 四角色
- **安全脱敏**: 4 层防线 (get_case_safe → timeline events → patient_state → case list filter)
- **AI 追溯**: 所有 LLM 调用记录 purpose/model/tokens/latency

## .gitignore

排除: `*.db*`, `records/*.json`, `*_events.json`, `logs/`, `dist/`, `node_modules/`, `__pycache__/`, `.env`
