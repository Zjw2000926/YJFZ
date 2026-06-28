import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  timeout: 120000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    // 401 直接跳转登录，不重试
    if (err.response?.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      window.location.href = "/login";
      return Promise.reject(err);
    }

    // 网络错误或 5xx 自动重试一次
    const config = err.config;
    if (!config || config._retryCount >= 1) {
      return Promise.reject(err);
    }

    const shouldRetry =
      !err.response ||
      err.response.status >= 500 ||
      err.code === "ECONNABORTED" ||
      err.code === "ERR_NETWORK";

    if (!shouldRetry) {
      return Promise.reject(err);
    }

    config._retryCount = (config._retryCount || 0) + 1;
    await new Promise((resolve) => setTimeout(resolve, 1000));
    return api(config);
  }
);

export function login(username, password) {
  return api.post("/auth/login", { username, password });
}

// ── 预检分诊训练 ──
export function getTriageCases() {
  return api.get("/triage/cases");
}

export function getTriageCaseDetail(externalId) {
  return api.get(`/triage/cases/${externalId}`);
}

export function startTriageTraining(caseExternalId, variantId = "default", options = {}) {
  return api.post("/triage/training/start", {
    case_external_id: caseExternalId,
    variant_id: variantId,
    mode: options.mode || "practice",
    time_limit_minutes: options.timeLimitMinutes || null,
    task_id: options.taskId || null,
  });
}

export function getTriageState(recordId) {
  return api.get(`/triage/training/${recordId}/state`);
}

export function getTriageRecords() {
  return api.get("/triage/training/records");
}

export function getTriageRecord(id) {
  return api.get(`/triage/training/records/${id}`);
}

export function sendTriageMessage(recordId, content) {
  return api.post(`/triage/training/${recordId}/message`, { content });
}

export function measureTriageVitals(recordId, measurementIds = []) {
  return api.post(`/triage/training/${recordId}/measure`, { measurement_ids: measurementIds });
}

export function submitTriage(recordId, payload) {
  return api.post(`/triage/training/${recordId}/submit`, payload);
}

// V4 动态病例
export function getTriageTimeline(recordId) {
  return api.get(`/triage/training/${recordId}/timeline`);
}
export function advanceTriageTimeline(recordId, minutes) {
  return api.post(`/triage/training/${recordId}/timeline/advance`, { minutes });
}
export function reassessTriagePatient(recordId, payload) {
  return api.post(`/triage/training/${recordId}/reassess`, payload);
}
export function getTriageCurrentState(recordId) {
  return api.get(`/triage/training/${recordId}/current-state`);
}
export function upgradeTriageLevel(recordId, payload) {
  return api.post(`/triage/training/${recordId}/upgrade`, payload);
}

// P1-A: 第一眼观察
export function observeTriagePatient(recordId, observationIds = []) {
  return api.post(`/triage/training/${recordId}/observe`, { observation_ids: observationIds });
}

// ── 教师管理 & 统计 ──
export function getTriageStatsOverview() {
  return api.get("/triage/stats/overview");
}
export function getAllTriageRecords() {
  return api.get("/triage/training/records/all");
}
export function getTriageCohorts() {
  return api.get("/triage/cohorts");
}
export function createTriageCohort(data) {
  return api.post("/triage/cohorts", data);
}
export function addTriageCohortMember(cohortId, data) {
  return api.post(`/triage/cohorts/${cohortId}/members`, data);
}
export function deleteTriageCohort(id) {
  return api.delete(`/triage/cohorts/${id}`);
}
export function bulkDeleteTriageCohorts(ids) {
  return api.post("/triage/cohorts/bulk-delete", { ids });
}
export function getTriageUsers(role) {
  return api.get("/triage/users", { params: role ? { role } : {} });
}
export function getTriageTasks() {
  return api.get("/triage/tasks");
}
export function createTriageTask(data) {
  return api.post("/triage/tasks", data);
}
export function deleteTriageTask(id) {
  return api.delete(`/triage/tasks/${id}`);
}
export function bulkDeleteTriageTasks(ids) {
  return api.post("/triage/tasks/bulk-delete", { ids });
}
export function releaseTriageTaskResults(id, data) {
  return api.patch(`/triage/tasks/${id}/release`, data);
}
export function deleteTriageRecord(id) {
  return api.delete(`/triage/training/records/${id}`);
}
export function bulkDeleteTriageRecords(ids) {
  return api.post("/triage/training/records/bulk-delete", { ids });
}
export function assignTriageTask(taskId, data) {
  return api.post(`/triage/tasks/${taskId}/assign`, data);
}
export function getTriageCaseReviews() {
  return api.get("/triage/cases/reviews");
}
export function getTriageCaseReviewDetail(caseId) {
  return api.get(`/triage/cases/${caseId}/review-detail`);
}
export function reviewTriageCase(caseId, data) {
  return api.post(`/triage/cases/${caseId}/review`, data);
}
export function getTriageLearningPath(userId) {
  return api.get(`/triage/learning-path/${userId}`);
}
export function getTriageScenarios() {
  return api.get("/triage/scenarios");
}
export function getTeacherReview(recordId) {
  return api.get(`/triage/training/${recordId}/rule-result`);
}
export function submitTeacherReview(recordId, data) {
  return api.post(`/triage/training/${recordId}/teacher-review`, data);
}
export function getTriageClassDashboard(cohortId) {
  return api.get(`/triage/stats/class-dashboard/${cohortId}`);
}
export function getTriageTaskAttempts(taskId) {
  return api.get(`/triage/tasks/${taskId}/attempts`);
}
export function getTriageAttempts() {
  return api.get("/triage/attempts");
}
export function exportTriageScoresCsv(params = {}) {
  return api.get("/triage/export/scores.csv", { params, responseType: "blob" });
}
export function exportTriageRecordPdf(recordId) {
  return api.get(`/triage/export/full-report/${recordId}.html`, { responseType: "blob" });
}
export function exportTriageRecordsPdf(ids = []) {
  return api.post("/triage/export/full-reports.html", { ids }, { responseType: "blob" });
}

// ── 动态训练 MVP 新增 ──
export function recordInitialDecision(recordId, data) {
  return api.post(`/triage/training/${recordId}/initial-decision`, data);
}
export function notifyDoctor(recordId, data) {
  return api.post(`/triage/training/${recordId}/notify-doctor`, data);
}
export function saveTrainingNotes(recordId, data) {
  return api.post(`/triage/training/${recordId}/save-notes`, data);
}
export function getDynamicTimeline(recordId) {
  return api.get(`/triage/training/${recordId}/timeline`);
}
