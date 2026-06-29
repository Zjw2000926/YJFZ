import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../../components/Layout";
import PageHeader from "../../components/ui/PageHeader";
import Card from "../../components/ui/Card";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import LoadingState from "../../components/ui/LoadingState";
import EmptyState from "../../components/ui/EmptyState";
import Modal from "../../components/ui/Modal";
import { getTriageTasks, getTriageCases, getTriageRecords } from "../../api";
import { ClipboardList, AlertTriangle } from "lucide-react";
import { isTrainingRecordExpired } from "../../utils/trainingTimer";

const MODES = { practice: "练习", exam: "考核", osce: "OSCE" };
const MODE_COLORS = { practice: "info", exam: "danger", osce: "warning" };

export default function TriageTasks({ user, onLogout }) {
  const [tasks, setTasks] = useState([]);
  const [cases, setCases] = useState([]);
  const [records, setRecords] = useState([]);
  const [selectedTask, setSelectedTask] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    Promise.all([
      getTriageTasks().then(r => setTasks(r.data.items || [])).catch(() => {}),
      getTriageCases().then(r => setCases(r.data.items || [])).catch(() => {}),
      getTriageRecords().then(r => setRecords(r.data.items || [])).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  if (loading) return <Layout user={user} onLogout={onLogout}><LoadingState /></Layout>;

  const caseMap = new Map(cases.map((c) => [c.external_id, c]));
  const currentUserId = Number(user?.id ?? user?.user_id);
  const getStartUrl = (task, caseId) => {
    const cid = caseId || task.case_external_ids?.[0];
    return `/triage/training/start?case=${cid}&mode=${task.mode}&time_limit=${task.time_limit_minutes || 8}&task_id=${task.id}`;
  };
  const getResumeUrl = (task, caseId, recordId) => {
    const query = `case=${caseId}&mode=${task.mode}&time_limit=${task.time_limit_minutes || 8}&task_id=${task.id}`;
    return `/triage/training/start?${query}&record_id=${recordId}`;
  };
  const myTasks = Number.isFinite(currentUserId)
    ? tasks.filter(t => t.assignments?.some(a => Number(a.user_id) === currentUserId))
    : tasks;
  const getCaseIds = (task) => task.case_external_ids || task.case_ids || [];
  const getSubmittedCaseRecord = (taskId, caseId) => records.find((record) => (
    record.task_id === taskId &&
    record.case_external_id === caseId &&
    ["submitted", "scored"].includes(record.status)
  ));
  const getInProgressCaseRecord = (task, caseId) => records.find((record) => (
    record.task_id === task.id &&
    record.case_external_id === caseId &&
    record.status === "in_progress" &&
    !isTrainingRecordExpired(record, task.time_limit_minutes)
  ));
  const getExpiredCaseRecord = (task, caseId) => records.find((record) => (
    record.task_id === task.id &&
    record.case_external_id === caseId &&
    record.status === "in_progress" &&
    isTrainingRecordExpired(record, task.time_limit_minutes)
  ));
  const getCompletedCount = (task) => getCaseIds(task).filter((caseId) => getSubmittedCaseRecord(task.id, caseId)).length;
  const startTask = (task) => {
    const caseIds = getCaseIds(task);
    if (caseIds.length === 0) return;
    setSelectedTask(task);
  };
  const selectedCaseIds = selectedTask ? getCaseIds(selectedTask) : [];

  return (
    <Layout user={user} onLogout={onLogout}>
      <PageHeader title="我的预检分诊任务" subtitle="教师分配的练习、考核和OSCE任务" icon={ClipboardList} backTo="/triage" />
      <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: 8, marginBottom: 16, fontSize: "0.72rem", color: "#991b1b" }}>
        仅用于教学训练，不用于真实临床分诊。
      </div>

      {myTasks.length === 0 && <EmptyState icon={ClipboardList} title="暂无任务" description="教师尚未分配预检分诊训练任务" />}

      {myTasks.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: "0.9rem", marginBottom: 8 }}>我的任务</h3>
          {myTasks.map(t => {
            const myAssign = t.assignments?.find(a => Number(a.user_id) === currentUserId);
            const caseIds = getCaseIds(t);
            const completedCount = getCompletedCount(t);
            const allCasesDone = caseIds.length > 0 && completedCount === caseIds.length;
            const actionText = allCasesDone ? "查看病例" : "选择病例";
            return (
              <Card key={t.id} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: "0.85rem" }}>{t.title}</div>
                    <div style={{ fontSize: "0.72rem", color: "#6b7280" }}>
                      <Badge variant={MODE_COLORS[t.mode] || "info"}>{MODES[t.mode] || t.mode}</Badge>
                      {" "}限时{t.time_limit_minutes || 8}分钟 · {(t.case_external_ids || []).length}题
                      {caseIds.length > 0 && <span style={{ marginLeft: 8 }}>已完成 {completedCount}/{caseIds.length}</span>}
                      {t.mode === "exam" && <span style={{ color: "#dc2626", marginLeft: 8 }}><AlertTriangle size={10} /> 提交后不可修改</span>}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      {allCasesDone && <Badge variant="success">已完成 {myAssign?.best_score ?? ""}分</Badge>}
                      <Button size="sm" onClick={() => startTask(t)} disabled={caseIds.length === 0}>{actionText}</Button>
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <Modal open={Boolean(selectedTask)} title={selectedTask ? `选择病例：${selectedTask.title}` : "选择病例"} onClose={() => setSelectedTask(null)} maxWidth={760}>
        {selectedTask && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontSize: "0.78rem", color: "#6b7280" }}>
              本任务包含 {selectedCaseIds.length} 个病例，请选择要先开始的病例。考核模式下不会显示提示和标准答案。
            </div>
            {selectedCaseIds.map((caseId, index) => {
              const c = caseMap.get(caseId);
              const doneRecord = getSubmittedCaseRecord(selectedTask.id, caseId);
              const inProgressRecord = getInProgressCaseRecord(selectedTask, caseId);
              const expiredRecord = getExpiredCaseRecord(selectedTask, caseId);
              const isDone = Boolean(doneRecord);
              const canContinue = Boolean(inProgressRecord);
              return (
                <div key={caseId} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 12, display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                  <div style={{ minWidth: 220 }}>
                    <div style={{ fontWeight: 700, fontSize: "0.86rem" }}>{index + 1}. {c?.display_name || caseId}</div>
                    <div style={{ fontSize: "0.72rem", color: "#6b7280", marginTop: 4 }}>
                      <Badge variant="info">训练病例</Badge>
                      {" "}难度 {c?.difficulty || "-"} · {caseId}
                      {isDone && <Badge variant="success" style={{ marginLeft: 6 }}>已完成 {doneRecord.total_score ?? "-"}分</Badge>}
                      {!isDone && expiredRecord && !canContinue && <Badge variant="warning" style={{ marginLeft: 6 }}>上次已超时</Badge>}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {isDone && (
                      <Button size="sm" variant="outline" onClick={() => navigate(`/triage/record/${doneRecord.id}`)}>查看报告</Button>
                    )}
                    <Button
                      size="sm"
                      disabled={isDone && selectedTask.mode === "exam" && !selectedTask.allow_retry}
                      onClick={() => navigate(canContinue ? getResumeUrl(selectedTask, caseId, inProgressRecord.id) : getStartUrl(selectedTask, caseId))}
                    >
                      {canContinue ? "继续" : expiredRecord ? "重新开始" : isDone ? "重新训练" : "开始"}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Modal>
    </Layout>
  );
}
