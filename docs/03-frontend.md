# 前端架构

## 目录结构

```
frontend/
├── index.html
├── package.json                # React 19, Vite 8, React Router 7
├── vite.config.js              # port:3010, proxy /api → :8010
├── vitest.config.js            # jsdom + Testing Library
├── playwright.config.js        # E2E (Chromium headless)
├── eslint.config.js
└── src/
    ├── App.jsx                 # 8 routes, 多角色守卫
    ├── api.js                  # 统一 axios (~35 API 函数)
    ├── components/
    │   ├── Layout.jsx
    │   ├── Toast.jsx / ToastContext.js / useToast.js
    │   ├── ConfirmDialog.jsx / ConfirmContext.js / useConfirm.js
    │   ├── ErrorBoundary.jsx
    │   ├── ui/ (Badge/Button/Card/EmptyState/FormField/LoadingState/Modal/PageHeader/StatCard/Table/Tabs)
    │   └── triage/
    │       ├── TriageScoreCard.jsx
    │       └── TriageTimelinePanel.jsx  # 水平时间轴 + T0/T15/T30 标记
    ├── pages/triage/
    │   ├── Login.jsx
    │   ├── TriageCaseSelect.jsx         # 动态/静态病例卡片
    │   ├── TriageTraining.jsx           # 静态训练页
    │   ├── TriageDynamicTraining.jsx    # 动态训练页 (分离初始/复评分诊, 复评时间选择, 通知医生 checkbox, textarea 说明)
    │   ├── TriageRecordDetail.jsx       # 报告页 (动态时间线 + 体征日志 + 初始/最终对比)
    │   ├── TriageAdmin.jsx              # 教师管理
    │   ├── TriageTasks.jsx              # 学生任务
    │   └── TriageLearningPath.jsx       # 学习路径
    ├── __tests__/ (4 文件, 26 tests)
    ├── e2e/ (1 文件, 3 tests)
    └── styles/triage.css
```

## 路由表

| 路径 | 页面 | 权限 |
|------|------|------|
| `/login` | Login | 公开 |
| `/triage` | TriageCaseSelect | 登录用户 |
| `/triage/training/start?case=X` | TriageTraining | student |
| `/triage/dynamic/start?case=X` | TriageDynamicTraining | student |
| `/triage/dynamic/:recordId` | TriageDynamicTraining (恢复) | student |
| `/triage/record/:id` | TriageRecordDetail | 登录用户 |
| `/triage/admin` | TriageAdmin | teacher/reviewer/admin |
| `/triage/tasks` | TriageTasks | student |
| `/triage/learning-path` | TriageLearningPath | 登录用户 |

## 统一 API 客户端

`src/api.js` 统一管理所有前端 API 调用：
- baseURL `/api` → Vite proxy → :8010
- 自动注入 Authorization header
- 401 清理 token 跳转登录
- 5xx 自动重试 1 次

**严格禁止**页面自建 axios 实例。已全部统一。

## 动态训练页 UI 结构

```
右侧面板:
├── 患者信息区 (当前状态/外观)
├── 时间轴面板 (T0/T15/T30 水平可视化)
├── 第一眼观察 (选择+记录)
├── 测量生命体征 (选择+测量全部+测量所选)
├── 分诊等级 + 就诊区域选择
├── 初始分诊区 (复评时间下拉 + 记录按钮)
├── 复评升级区 (通知医生 checkbox + 执行复评 + 通知医生按钮)
├── 记录说明 (textarea 替代 prompt)
└── 提交分诊按钮
```

## 测试 (29 tests 总计)

| 层级 | 文件 | 测试 |
|------|------|------|
| Vitest | api.test.js | 9 |
| Vitest | App.test.jsx | 5 |
| Vitest | TriageCaseSelect.test.jsx | 3 |
| Vitest | TriageDynamicTraining.test.jsx | 9 |
| E2E | dynamic-mvp.spec.js | **3** |
