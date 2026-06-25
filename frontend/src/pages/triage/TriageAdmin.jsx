import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import Layout from "../../components/Layout";
import PageHeader from "../../components/ui/PageHeader";
import Card from "../../components/ui/Card";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Tabs from "../../components/ui/Tabs";
import Table from "../../components/ui/Table";
import StatCard from "../../components/ui/StatCard";
import Modal from "../../components/ui/Modal";
import FormField from "../../components/ui/FormField";
import LoadingState from "../../components/ui/LoadingState";
import EmptyState from "../../components/ui/EmptyState";
import { useToast } from "../../components/useToast";
import {
  getTriageStatsOverview, getAllTriageRecords, getTriageCases, getTriageCohorts, createTriageCohort,
  getTriageTasks, createTriageTask, deleteTriageTask, bulkDeleteTriageTasks, bulkDeleteTriageCohorts,
  releaseTriageTaskResults,
  bulkDeleteTriageRecords, getTriageCaseReviews, getTriageCaseReviewDetail, reviewTriageCase,
  getTriageScenarios, getTriageUsers, addTriageCohortMember, exportTriageScoresCsv,
} from "../../api";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell, Legend, ComposedChart,
} from "recharts";

const MODES = { practice: "练习", exam: "考核", osce: "OSCE" };
const REVIEW_ST = { draft: "草稿", pending: "审核中", pending_review: "待审核", approved: "已通过", rejected: "已拒绝", archived: "已归档" };
const PAGE_SIZE_OPTIONS = [10, 20, 50];
const TAB_DATA_KEYS = {
  overview: ["stats"],
  cohorts: ["cohorts", "users"],
  cases: ["cases", "reviews"],
  tasks: ["tasks", "cohorts", "cases"],
  records: ["records"],
  reviews: ["reviews"],
  analytics: ["stats"],
  export: ["records", "tasks"],
};

function usePagination(items, initialPageSize = 10) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSizeValue] = useState(initialPageSize);
  const total = items?.length || 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.min(page, pageCount);
  const start = (currentPage - 1) * pageSize;
  const pageItems = useMemo(() => (items || []).slice(start, start + pageSize), [items, start, pageSize]);

  const setPageSize = (value) => {
    setPageSizeValue(Number(value));
    setPage(1);
  };

  return { page: currentPage, pageSize, total, pageCount, pageItems, setPage, setPageSize };
}

function PaginationControls({ page, pageSize, total, pageCount, onPageChange, onPageSizeChange }) {
  const hasItems = total > 0;
  const start = hasItems ? (page - 1) * pageSize + 1 : 0;
  const end = hasItems ? Math.min(total, page * pageSize) : 0;
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginTop: 10, flexWrap: "wrap", fontSize: "0.75rem", color: "#6b7280" }}>
      <span>显示 {start}-{end} / 共 {total} 条</span>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <label>
          每页{" "}
          <select value={pageSize} onChange={(e) => onPageSizeChange(e.target.value)} style={{ padding: "4px 6px", border: "1px solid #d1d5db", borderRadius: 4 }}>
            {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPageChange(1)}>首页</Button>
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</Button>
        <span>第 {page} / {pageCount} 页</span>
        <Button size="sm" variant="outline" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>下一页</Button>
        <Button size="sm" variant="outline" disabled={page >= pageCount} onClick={() => onPageChange(pageCount)}>末页</Button>
      </div>
    </div>
  );
}

function PaginatedTable({ columns, data, rowKey, emptyState, pageSize = 10 }) {
  const pager = usePagination(data || [], pageSize);
  return (
    <>
      <Table columns={columns} data={pager.pageItems} rowKey={rowKey} emptyState={emptyState} />
      <PaginationControls
        page={pager.page}
        pageSize={pager.pageSize}
        total={pager.total}
        pageCount={pager.pageCount}
        onPageChange={pager.setPage}
        onPageSizeChange={pager.setPageSize}
      />
    </>
  );
}

function BulkActionBar({ selectedCount, pageTotal, allPageSelected, onTogglePage, onClear, onDelete, deleteLabel = "批量删除" }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "8px 10px", marginBottom: 10, border: "1px solid #e5e7eb", borderRadius: 8, background: "#f9fafb", flexWrap: "wrap" }}>
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.78rem", color: "#374151" }}>
        <input type="checkbox" checked={pageTotal > 0 && allPageSelected} disabled={pageTotal === 0} onChange={onTogglePage} />
        选择当前页
      </label>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.76rem", color: "#6b7280" }}>已选择 {selectedCount} 项</span>
        <Button size="sm" variant="outline" disabled={selectedCount === 0} onClick={onClear}>清空选择</Button>
        <Button size="sm" variant="danger" disabled={selectedCount === 0} onClick={onDelete}>{deleteLabel}</Button>
      </div>
    </div>
  );
}

export default function TriageAdmin({ user, onLogout }) {
  const [activeTab, setActiveTab] = useState("overview");
  const [stats, setStats] = useState(null);
  const [records, setRecords] = useState([]);
  const [cases, setCases] = useState([]);
  const [cohorts, setCohorts] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [users, setUsers] = useState([]);
  const [loaded, setLoaded] = useState({});
  const [sectionLoading, setSectionLoading] = useState({});
  const inFlightRef = useRef({});
  const toast = useToast();

  const loadData = useCallback(async (key, force = false) => {
    if (!force && loaded[key]) return;
    if (!force && inFlightRef.current[key]) return inFlightRef.current[key];
    const fetchers = {
      stats: () => getTriageStatsOverview().then(r => setStats(r.data)),
      records: () => getAllTriageRecords().then(r => setRecords(r.data.items || [])),
      cases: () => getTriageCases().then(r => setCases(r.data.items || [])),
      cohorts: () => getTriageCohorts().then(r => setCohorts(r.data.items || [])),
      tasks: () => getTriageTasks().then(r => setTasks(r.data.items || [])),
      reviews: () => getTriageCaseReviews().then(r => setReviews(r.data.items || [])),
      users: () => getTriageUsers("student").then(r => setUsers(r.data.items || [])),
    };
    if (!fetchers[key]) return;
    setSectionLoading((prev) => ({ ...prev, [key]: true }));
    const request = (async () => {
      await fetchers[key]();
      setLoaded((prev) => ({ ...prev, [key]: true }));
    })();
    inFlightRef.current[key] = request;
    try {
      await request;
    } catch {
      toast.error("加载数据失败");
    } finally {
      delete inFlightRef.current[key];
      setSectionLoading((prev) => ({ ...prev, [key]: false }));
    }
  }, [loaded, toast]);

  useEffect(() => {
    const keys = TAB_DATA_KEYS[activeTab] || [];
    keys.forEach((key) => loadData(key));
  }, [activeTab, loadData]);

  const refresh = useCallback((key) => {
    return loadData(key, true);
  }, [loadData]);

  const isInitialLoading = (...keys) => keys.some((key) => sectionLoading[key] && !loaded[key]);

  const tabs = [
    { key: "overview", label: "教师首页" },
    { key: "cohorts", label: "班级管理", count: loaded.cohorts ? cohorts.length : null },
    { key: "cases", label: "病例库", count: loaded.cases ? cases.length : null },
    { key: "tasks", label: "任务发布", count: loaded.tasks ? tasks.length : null },
    { key: "records", label: "成绩报告", count: loaded.records ? records.length : null },
    { key: "reviews", label: "专家复核", count: loaded.reviews ? reviews.length : null },
    { key: "analytics", label: "数据看板" },
    { key: "export", label: "导出" },
  ];

  return (
    <Layout user={user} onLogout={onLogout}>
      <PageHeader title="预检分诊管理" subtitle="教师端 — 教学管理与数据分析" backTo="/triage" />
      <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: 10, marginBottom: 12, fontSize: "0.78rem", color: "#991b1b" }}>
        本系统仅用于护理教育训练，不用于真实临床分诊或诊疗决策。
      </div>
      <Tabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />
      <div style={{ marginTop: 16 }}>
        {activeTab === "overview" && (isInitialLoading("stats") ? <LoadingState /> : <OverviewTab stats={stats} />)}
        {activeTab === "tasks" && (isInitialLoading("tasks", "cohorts", "cases") ? <LoadingState /> : <TasksTab tasks={tasks} cohorts={cohorts} cases={cases} refresh={() => refresh("tasks")} toast={toast} />)}
        {activeTab === "records" && (isInitialLoading("records") ? <LoadingState /> : <RecordsTab records={records} refresh={() => refresh("records")} toast={toast} />)}
        {activeTab === "cohorts" && (isInitialLoading("cohorts", "users") ? <LoadingState /> : <CohortsTab cohorts={cohorts} users={users} refresh={() => { refresh("cohorts"); refresh("users"); }} toast={toast} />)}
        {activeTab === "cases" && (isInitialLoading("cases", "reviews") ? <LoadingState /> : <CasesTab cases={cases} reviews={reviews} refresh={() => { refresh("cases"); refresh("reviews"); }} toast={toast} />)}
        {activeTab === "reviews" && (isInitialLoading("reviews") ? <LoadingState /> : <ReviewsTab reviews={reviews} cases={cases} refresh={() => refresh("reviews")} toast={toast} />)}
        {activeTab === "scenarios" && <ScenariosTab />}
        {activeTab === "analytics" && (isInitialLoading("stats") ? <LoadingState /> : <AnalyticsTab stats={stats} />)}
        {activeTab === "export" && (isInitialLoading("records", "tasks") ? <LoadingState /> : <ExportTab records={records} tasks={tasks} />)}
      </div>
    </Layout>
  );
}

function OverviewTab({ stats }) {
  if (!stats) return <EmptyState title="暂无数据" />;
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10, marginBottom: 16 }}>
        <StatCard value={stats.total_records || 0} label="训练总次数" color="blue" />
        <StatCard value={stats.avg_score || "-"} label="平均分" color="teal" />
        <StatCard value={`${Math.round((stats.triage_accuracy || 0) * 100)}%`} label="分诊准确率" color="green" />
        <StatCard value={`${Math.round((stats.under_triage_rate || 0) * 100)}%`} label="低估分诊率" color="red" />
        <StatCard value={`${Math.round((stats.reassessment_rate || 0) * 100)}%`} label="复评完成率" color="amber" />
        <StatCard value={`${Math.round((stats.critical_recognition_rate || 0) * 100)}%`} label="危重症识别率" color="green" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: 12 }}>
        <Card title="训练趋势 (次数 & 平均分)">
          {stats.recent_trend?.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <ComposedChart data={stats.recent_trend.slice(-14)}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="right" orientation="right" domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar yAxisId="left" dataKey="count" fill="#2563eb" name="训练次数" radius={[4, 4, 0, 0]} />
                <Line yAxisId="right" type="monotone" dataKey="avg_score" stroke="#16a34a" name="平均分" strokeWidth={2} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <EmptyState title="暂无趋势" />}
        </Card>
        <Card title="分诊表现占比">
          {stats.pass_distribution ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={stats.pass_distribution} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                  {stats.pass_distribution.map((_, i) => (
                    <Cell key={i} fill={["#16a34a", "#2563eb", "#d97706", "#dc2626"][i % 4]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : <EmptyState title="暂无分诊数据" />}
        </Card>
      </div>
    </div>
  );
}

function TasksTab({ tasks, cohorts, cases, refresh, toast }) {
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ title: "", cohort_id: "", mode: "practice", case_external_ids: [], time_limit_minutes: 8 });
  const [caseFilter, setCaseFilter] = useState("");
  const [selectedTaskIds, setSelectedTaskIds] = useState([]);

  const toggleCase = (id) => {
    setForm(prev => ({
      ...prev,
      case_external_ids: prev.case_external_ids.includes(id)
        ? prev.case_external_ids.filter(x => x !== id)
        : [...prev.case_external_ids, id],
    }));
  };

  const handleCreate = async () => {
    if (!form.title.trim()) { toast.warning("请输入任务名称"); return; }
    if (!form.cohort_id) { toast.warning("请选择班级"); return; }
    if (!form.case_external_ids.length) { toast.warning("请选择至少一个病例"); return; }
    try {
      await createTriageTask(form);
      toast.success("任务已创建");
      setShowCreate(false); setForm({ title: "", cohort_id: "", mode: "practice", case_external_ids: [], time_limit_minutes: 8 });
      refresh();
    } catch { toast.error("创建失败"); }
  };

  const taskPager = usePagination(tasks || [], 10);
  const pageTaskIds = taskPager.pageItems.map((task) => task.id).filter(Boolean);
  const selectedTaskSet = useMemo(() => new Set(selectedTaskIds), [selectedTaskIds]);
  const allPageTasksSelected = pageTaskIds.length > 0 && pageTaskIds.every((id) => selectedTaskSet.has(id));

  const toggleTask = (id) => {
    setSelectedTaskIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  };

  const toggleTaskPage = () => {
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      if (allPageTasksSelected) {
        pageTaskIds.forEach((id) => next.delete(id));
      } else {
        pageTaskIds.forEach((id) => next.add(id));
      }
      return [...next];
    });
  };

  const handleSingleDelete = async (id) => {
    if (!id || !confirm("确定删除此任务？历史成绩报告不会被自动删除。")) return;
    try {
      const res = await deleteTriageTask(id);
      toast.success(`已删除 ${res.data?.deleted || 0} 个任务`);
      setSelectedTaskIds((prev) => prev.filter((item) => item !== id));
      await refresh();
    } catch (err) {
      toast.error(err.response?.status === 404 ? "任务不存在或已删除" : "删除失败");
    }
  };

  const handleBulkDelete = async () => {
    const ids = selectedTaskIds.filter(Boolean);
    if (!ids.length) return;
    if (!confirm(`确定删除已选择的 ${ids.length} 个任务？历史成绩报告不会被自动删除。`)) return;
    try {
      const res = await bulkDeleteTriageTasks(ids);
      toast.success(`已删除 ${res.data?.deleted || 0} 个任务`);
      setSelectedTaskIds((prev) => prev.filter((id) => !ids.includes(id)));
      await refresh();
    } catch (err) {
      toast.error(err.response?.status === 404 ? "未找到可删除的任务" : "批量删除失败");
    }
  };

  const isScoreReleased = (task) => task.mode === "practice" || task.score_released || task.show_feedback_immediately;
  const isFeedbackReleased = (task) => task.mode === "practice" || task.show_feedback_immediately;
  const isAnswerReleased = (task) => Boolean(task.show_standard_answer);

  const handleRelease = async (task, type) => {
    if (!task?.id) return;
    const payload = {};
    if (type === "feedback") {
      payload.score_released = true;
      payload.feedback_released = true;
      payload.release_note = "教师发布成绩与详细反馈";
    } else if (type === "answer") {
      if (!confirm("确定向学员开放标准答案吗？考核任务开放后学员可查看标准分诊依据。")) return;
      payload.standard_answer_released = true;
      payload.release_note = "教师发布标准答案";
    } else if (type === "hide") {
      if (!confirm("确定隐藏该任务的学生端成绩、详细反馈和标准答案吗？教师端仍可查看。")) return;
      payload.score_released = false;
      payload.feedback_released = false;
      payload.standard_answer_released = false;
      payload.release_note = "教师隐藏考核结果";
    }
    try {
      await releaseTriageTaskResults(task.id, payload);
      toast.success("任务发布设置已更新");
      await refresh();
    } catch (err) {
      toast.error(err.response?.data?.detail || "更新发布设置失败");
    }
  };

  const approvedCases = (cases || []).filter((c) => c.review_status === "approved" || c.is_available_for_training);
  const filteredCases = caseFilter
    ? approvedCases.filter(c => c.external_id.includes(caseFilter) || c.display_name?.includes(caseFilter))
    : approvedCases;
  const casePager = usePagination(filteredCases, 10);

  const cols = [
    { key: "select", label: "", width: 36, render: (_, row) => (
      <input type="checkbox" checked={selectedTaskSet.has(row.id)} onChange={() => toggleTask(row.id)} onClick={(e) => e.stopPropagation()} />
    ) },
    { key: "title", label: "任务", width: 150 },
    { key: "mode", label: "模式", width: 60, render: (v) => <Badge variant={v === "exam" ? "danger" : v === "osce" ? "warning" : "info"}>{MODES[v] || v}</Badge> },
    { key: "cohort_id", label: "班级", width: 80 },
    { key: "case_external_ids", label: "病例", width: 80, render: (v) => (v || []).length },
    { key: "status", label: "状态", width: 60 },
    { key: "assignments", label: "进度", width: 60, render: (v) => `${(v || []).filter(a => a.status === "scored").length}/${(v || []).length}` },
    { key: "release", label: "开放", width: 140, render: (_, row) => (
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        <Badge variant={isScoreReleased(row) ? "success" : "neutral"}>成绩</Badge>
        <Badge variant={isFeedbackReleased(row) ? "success" : "neutral"}>反馈</Badge>
        <Badge variant={isAnswerReleased(row) ? "warning" : "neutral"}>答案</Badge>
      </div>
    ) },
    { key: "actions", label: "操作", width: 240, render: (_, row) => (
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        <Button size="sm" variant="outline" onClick={() => handleRelease(row, "feedback")}>发布成绩反馈</Button>
        <Button size="sm" variant="outline" onClick={() => handleRelease(row, "answer")}>发布答案</Button>
        <Button size="sm" variant="outline" onClick={() => handleRelease(row, "hide")}>隐藏</Button>
        <Button size="sm" variant="danger" onClick={() => handleSingleDelete(row.id)}>删除</Button>
      </div>
    )},
  ];

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Button onClick={() => setShowCreate(true)}>创建任务</Button>
      </div>
      <BulkActionBar
        selectedCount={selectedTaskIds.length}
        pageTotal={pageTaskIds.length}
        allPageSelected={allPageTasksSelected}
        onTogglePage={toggleTaskPage}
        onClear={() => setSelectedTaskIds([])}
        onDelete={handleBulkDelete}
        deleteLabel="批量删除任务"
      />
      <Table columns={cols} data={taskPager.pageItems} rowKey="id" emptyState={<EmptyState title="暂无任务" />} />
      <PaginationControls
        page={taskPager.page}
        pageSize={taskPager.pageSize}
        total={taskPager.total}
        pageCount={taskPager.pageCount}
        onPageChange={taskPager.setPage}
        onPageSizeChange={taskPager.setPageSize}
      />
      <Modal open={showCreate} title="创建训练任务" onClose={() => setShowCreate(false)}>
          <FormField label="任务名称"><input value={form.title} onChange={e => setForm({...form, title: e.target.value})} style={{ width: "100%", padding: 6 }} /></FormField>
          <FormField label="班级"><select value={form.cohort_id} onChange={e => setForm({...form, cohort_id: e.target.value})} style={{ width: "100%", padding: 6 }}><option value="">选择班级</option>{cohorts.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></FormField>
          <FormField label="模式"><select value={form.mode} onChange={e => setForm({...form, mode: e.target.value})} style={{ width: "100%", padding: 6 }}>{Object.entries(MODES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></FormField>
          <FormField label={`病例选择 (已选 ${form.case_external_ids.length} 个)`}>
            <input placeholder="搜索病例 ID 或名称..." value={caseFilter} onChange={e => setCaseFilter(e.target.value)}
              style={{ width: "100%", padding: 6, marginBottom: 6, fontSize: "0.75rem" }} />
            <div style={{ maxHeight: 200, overflow: "auto", border: "1px solid #e5e7eb", borderRadius: 4, padding: 4 }}>
              {casePager.pageItems.map(c => (
                <label key={c.external_id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "3px 4px", fontSize: "0.72rem", cursor: "pointer", background: form.case_external_ids.includes(c.external_id) ? "#eff6ff" : "transparent" }}>
                  <input type="checkbox" checked={form.case_external_ids.includes(c.external_id)} onChange={() => toggleCase(c.external_id)} />
                  <span style={{ fontWeight: 600, width: 85 }}>{c.external_id}</span>
                  <span style={{ flex: 1 }}>{c.display_name?.substring(0, 20)}</span>
                  <Badge variant={c.difficulty >= 3 ? "danger" : c.difficulty >= 2 ? "warning" : "success"}>{c.difficulty || 1}</Badge>
                  {c.is_dynamic && <Badge variant="info" style={{ fontSize: "0.55rem" }}>动态</Badge>}
                </label>
              ))}
              {filteredCases.length === 0 && <div style={{ padding: 8, fontSize: "0.7rem", color: "#9ca3af" }}>暂无已审核通过病例，请先在病例库完成审核</div>}
            </div>
            <PaginationControls
              page={casePager.page}
              pageSize={casePager.pageSize}
              total={casePager.total}
              pageCount={casePager.pageCount}
              onPageChange={casePager.setPage}
              onPageSizeChange={casePager.setPageSize}
            />
          </FormField>
          <FormField label="时限(分钟)"><input type="number" value={form.time_limit_minutes} onChange={e => setForm({...form, time_limit_minutes: parseInt(e.target.value) || 8})} style={{ width: 80, padding: 6 }} /></FormField>
          <Button onClick={handleCreate}>创建</Button>
        </Modal>
    </div>
  );
}

function RecordsTab({ records, refresh, toast }) {
  const [selectedRecordIds, setSelectedRecordIds] = useState([]);
  const recordPager = usePagination(records || [], 20);
  const pageRecordIds = recordPager.pageItems.map((record) => record.id).filter(Boolean);
  const selectedRecordSet = useMemo(() => new Set(selectedRecordIds), [selectedRecordIds]);
  const allPageRecordsSelected = pageRecordIds.length > 0 && pageRecordIds.every((id) => selectedRecordSet.has(id));

  const toggleRecord = (id) => {
    setSelectedRecordIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  };

  const toggleRecordPage = () => {
    setSelectedRecordIds((prev) => {
      const next = new Set(prev);
      if (allPageRecordsSelected) {
        pageRecordIds.forEach((id) => next.delete(id));
      } else {
        pageRecordIds.forEach((id) => next.add(id));
      }
      return [...next];
    });
  };

  const handleBulkDelete = async () => {
    const ids = selectedRecordIds.filter(Boolean);
    if (!ids.length) return;
    if (!confirm(`确定删除已选择的 ${ids.length} 份成绩报告？此操作会删除训练报告快照。`)) return;
    try {
      const res = await bulkDeleteTriageRecords(ids);
      toast.success(`已删除 ${res.data?.deleted || 0} 份成绩报告`);
      setSelectedRecordIds((prev) => prev.filter((id) => !ids.includes(id)));
      await refresh();
    } catch (err) {
      toast.error(err.response?.status === 404 ? "未找到可删除的成绩报告" : "批量删除失败");
    }
  };

  const handleSingleDelete = async (id) => {
    if (!id || !confirm("确定删除此成绩报告？此操作会删除训练报告快照。")) return;
    try {
      const res = await bulkDeleteTriageRecords([id]);
      toast.success(`已删除 ${res.data?.deleted || 0} 份成绩报告`);
      setSelectedRecordIds((prev) => prev.filter((item) => item !== id));
      await refresh();
    } catch (err) {
      toast.error(err.response?.status === 404 ? "成绩报告不存在或已删除" : "删除失败");
    }
  };

  const cols = [
    { key: "select", label: "", width: 36, render: (_, row) => (
      <input type="checkbox" checked={selectedRecordSet.has(row.id)} onChange={() => toggleRecord(row.id)} onClick={(e) => e.stopPropagation()} />
    ) },
    { key: "user_display_name", label: "学员", width: 70 },
    { key: "case_external_id", label: "病例", width: 90 },
    { key: "status", label: "状态", width: 50 },
    { key: "total_score", label: "分数", width: 45, render: (v) => v != null ? `${v}分` : "-" },
    { key: "pass_status", label: "评级", width: 50, render: (v) => v ? <Badge variant={v === "fail" ? "danger" : v === "excellent" ? "success" : "info"}>{v}</Badge> : "-" },
    { key: "started_at", label: "时间", width: 90, render: (v) => v?.substring(0, 16) },
    { key: "actions", label: "报告", width: 120, render: (_, r) => (
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <Button size="sm" variant="outline" onClick={() => { window.location.href = `/triage/record/${r.id}`; }}>查看</Button>
        <Button size="sm" variant="danger" onClick={() => handleSingleDelete(r.id)}>删除</Button>
      </div>
    )},
  ];
  return (
    <>
      <BulkActionBar
        selectedCount={selectedRecordIds.length}
        pageTotal={pageRecordIds.length}
        allPageSelected={allPageRecordsSelected}
        onTogglePage={toggleRecordPage}
        onClear={() => setSelectedRecordIds([])}
        onDelete={handleBulkDelete}
        deleteLabel="批量删除报告"
      />
      <Table columns={cols} data={recordPager.pageItems} rowKey="id" emptyState={<EmptyState title="暂无记录" />} />
      <PaginationControls
        page={recordPager.page}
        pageSize={recordPager.pageSize}
        total={recordPager.total}
        pageCount={recordPager.pageCount}
        onPageChange={recordPager.setPage}
        onPageSizeChange={recordPager.setPageSize}
      />
    </>
  );
}

function CohortsTab({ cohorts, users, refresh, toast }) {
  const [show, setShow] = useState(false);
  const [name, setName] = useState("");
  const [selectedStudents, setSelectedStudents] = useState({});
  const [selectedCohortIds, setSelectedCohortIds] = useState([]);
  const pager = usePagination(cohorts || [], 10);
  const pageCohortIds = pager.pageItems.map((cohort) => cohort.id).filter(Boolean);
  const selectedCohortSet = useMemo(() => new Set(selectedCohortIds), [selectedCohortIds]);
  const allPageCohortsSelected = pageCohortIds.length > 0 && pageCohortIds.every((id) => selectedCohortSet.has(id));
  const handleCreateCohort = async () => {
    if (!name.trim()) { toast.warning("请输入班级名称"); return; }
    try { await createTriageCohort({ name: name.trim() }); toast.success("班级已创建"); setShow(false); refresh(); } catch { toast.error("失败"); }
  };
  const handleAddStudent = async (cohortId) => {
    const userId = selectedStudents[cohortId];
    if (!userId) { toast.warning("请选择学员"); return; }
    try {
      await addTriageCohortMember(cohortId, { user_id: Number(userId) });
      toast.success("学员已加入班级");
      refresh();
    } catch { toast.error("添加失败"); }
  };

  const toggleCohort = (id) => {
    setSelectedCohortIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  };

  const toggleCohortPage = () => {
    setSelectedCohortIds((prev) => {
      const next = new Set(prev);
      if (allPageCohortsSelected) {
        pageCohortIds.forEach((id) => next.delete(id));
      } else {
        pageCohortIds.forEach((id) => next.add(id));
      }
      return [...next];
    });
  };

  const handleDeleteCohorts = async (ids) => {
    const targetIds = ids.filter(Boolean);
    if (!targetIds.length) return;
    if (!confirm(`确定删除 ${targetIds.length} 个班级？任务和历史报告不会被自动删除。`)) return;
    try {
      const res = await bulkDeleteTriageCohorts(targetIds);
      toast.success(`已删除 ${res.data?.deleted || 0} 个班级`);
      setSelectedCohortIds((prev) => prev.filter((id) => !targetIds.includes(id)));
      await refresh();
    } catch (err) {
      toast.error(err.response?.status === 404 ? "未找到可删除的班级" : "删除失败");
    }
  };
  return (
    <div>
      <Button onClick={() => setShow(true)} style={{ marginBottom: 12 }}>创建班级</Button>
      <BulkActionBar
        selectedCount={selectedCohortIds.length}
        pageTotal={pageCohortIds.length}
        allPageSelected={allPageCohortsSelected}
        onTogglePage={toggleCohortPage}
        onClear={() => setSelectedCohortIds([])}
        onDelete={() => handleDeleteCohorts(selectedCohortIds)}
        deleteLabel="批量删除班级"
      />
      {pager.pageItems.map(c => (
        <Card key={c.id} title={c.name} style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.78rem", color: "#374151" }}>
              <input type="checkbox" checked={selectedCohortSet.has(c.id)} onChange={() => toggleCohort(c.id)} />
              选择
            </label>
            <Button size="sm" variant="danger" onClick={() => handleDeleteCohorts([c.id])}>删除班级</Button>
          </div>
          <div style={{ fontSize: "0.78rem", color: "#6b7280", marginBottom: 8 }}>{c.description} · {c.members?.length || 0} 名学员</div>
          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <select value={selectedStudents[c.id] || ""} onChange={e => setSelectedStudents(prev => ({ ...prev, [c.id]: e.target.value }))}
              style={{ padding: 6, minWidth: 180, border: "1px solid #d1d5db", borderRadius: 6 }}>
              <option value="">选择学员</option>
              {(users || []).map(u => <option key={u.id} value={u.id}>{u.display_name || u.name} ({u.username})</option>)}
            </select>
            <Button size="sm" onClick={() => handleAddStudent(c.id)}>添加学员</Button>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {(c.members || []).map(m => <Badge key={m.user_id} variant="info">{m.user_name || m.user_id}</Badge>)}
          </div>
        </Card>
      ))}
      {cohorts.length === 0 && <EmptyState title="暂无班级" />}
      <PaginationControls
        page={pager.page}
        pageSize={pager.pageSize}
        total={pager.total}
        pageCount={pager.pageCount}
        onPageChange={pager.setPage}
        onPageSizeChange={pager.setPageSize}
      />
      <Modal open={show} title="创建班级" onClose={() => setShow(false)}><FormField label="名称"><input value={name} onChange={e => setName(e.target.value)} style={{ width: "100%", padding: 6 }} /></FormField><Button onClick={handleCreateCohort}>创建</Button></Modal>
    </div>
  );
}

function CasesTab({ cases, reviews, refresh, toast }) {
  const [detail, setDetail] = useState({ open: false, loading: false, caseData: null });
  const [reviewComment, setReviewComment] = useState("");
  const statusMap = {};
  reviews.forEach(r => { statusMap[r.case_id] = r.status; });
  const handleReview = async (caseId, status, comment = "") => {
    try {
      await reviewTriageCase(caseId, { status, comment });
      toast.success(`${REVIEW_ST[status]}`);
      refresh();
      if (detail.open) {
        setDetail((prev) => ({
          ...prev,
          caseData: prev.caseData ? { ...prev.caseData, review: { ...(prev.caseData.review || {}), status, comment, review_comments: comment } } : prev.caseData,
        }));
      }
    } catch { toast.error("失败"); }
  };
  const openDetail = async (caseId) => {
    setDetail({ open: true, loading: true, caseData: null });
    setReviewComment("");
    try {
      const res = await getTriageCaseReviewDetail(caseId);
      const caseData = res.data.case;
      setDetail({ open: true, loading: false, caseData });
      setReviewComment(caseData.review?.review_comments || caseData.review?.comment || "");
    } catch {
      toast.error("病例详情加载失败");
      setDetail({ open: false, loading: false, caseData: null });
    }
  };
  const cols = [
    { key: "external_id", label: "ID", width: 90 },
    { key: "display_name", label: "名称", width: 140 },
    { key: "difficulty", label: "难度", width: 45, render: (v) => <Badge variant={v >= 3 ? "danger" : "success"}>{v}</Badge> },
    { key: "review_status", label: "审核", width: 60, render: (_, r) => {
      const s = statusMap[r.external_id] || r.review_status || "draft";
      return <Badge variant={s === "approved" ? "success" : s === "rejected" ? "danger" : "warning"}>{REVIEW_ST[s]}</Badge>;
    }},
    { key: "actions", label: "操作", width: 80, render: (_, r) => (
      <div style={{ display: "flex", gap: 4 }}>
        <Button size="sm" variant="outline" onClick={() => openDetail(r.external_id)}>详情</Button>
        <Button size="sm" variant="outline" onClick={() => handleReview(r.external_id, "approved")}>通过</Button>
        <Button size="sm" variant="danger" onClick={() => handleReview(r.external_id, "rejected")}>拒绝</Button>
      </div>
    )},
  ];
  return (
    <>
      <PaginatedTable columns={cols} data={cases} rowKey="external_id" emptyState={<EmptyState title="暂无病例" />} pageSize={20} />
      <CaseReviewDetailModal
        detail={detail}
        comment={reviewComment}
        onCommentChange={setReviewComment}
        onClose={() => setDetail({ open: false, loading: false, caseData: null })}
        onApprove={() => detail.caseData && handleReview(detail.caseData.external_id, "approved", reviewComment)}
        onReject={() => detail.caseData && handleReview(detail.caseData.external_id, "rejected", reviewComment)}
      />
    </>
  );
}

function ReviewsTab({ reviews, cases, refresh, toast }) {
  const [detail, setDetail] = useState({ open: false, loading: false, caseData: null });
  const [reviewComment, setReviewComment] = useState("");
  if (reviews.length === 0) return <EmptyState title="暂无审核记录" />;
  const caseNameMap = Object.fromEntries((cases || []).map((item) => [item.external_id, item.display_name]));
  const openDetail = async (caseId) => {
    setDetail({ open: true, loading: true, caseData: null });
    setReviewComment("");
    try {
      const res = await getTriageCaseReviewDetail(caseId);
      const caseData = res.data.case;
      setDetail({ open: true, loading: false, caseData });
      setReviewComment(caseData.review?.review_comments || caseData.review?.comment || "");
    } catch {
      toast.error("病例详情加载失败");
      setDetail({ open: false, loading: false, caseData: null });
    }
  };
  const handleReview = async (caseId, status) => {
    try {
      await reviewTriageCase(caseId, { status, comment: reviewComment });
      toast.success(`${REVIEW_ST[status]}`);
      refresh();
      setDetail((prev) => ({
        ...prev,
        caseData: prev.caseData ? { ...prev.caseData, review: { ...(prev.caseData.review || {}), status, comment: reviewComment, review_comments: reviewComment } } : prev.caseData,
      }));
    } catch { toast.error("失败"); }
  };
  const cols = [
    { key: "case_id", label: "病例", width: 140, render: (v) => <span>{caseNameMap[v] || v}</span> },
    { key: "status", label: "状态", width: 60, render: (v) => <Badge variant={v === "approved" ? "success" : v === "rejected" ? "danger" : "warning"}>{REVIEW_ST[v] || v}</Badge> },
    { key: "comment", label: "备注", width: 150 },
    { key: "reviewed_at", label: "审核时间", width: 100, render: (v) => v?.substring(0, 16) },
    { key: "actions", label: "操作", width: 80, render: (_, r) => <Button size="sm" variant="outline" onClick={() => openDetail(r.case_id)}>查看病例</Button> },
  ];
  return (
    <>
      <PaginatedTable columns={cols} data={reviews} rowKey="id" emptyState={<EmptyState title="暂无审核记录" />} pageSize={20} />
      <CaseReviewDetailModal
        detail={detail}
        comment={reviewComment}
        onCommentChange={setReviewComment}
        onClose={() => setDetail({ open: false, loading: false, caseData: null })}
        onApprove={() => detail.caseData && handleReview(detail.caseData.external_id, "approved")}
        onReject={() => detail.caseData && handleReview(detail.caseData.external_id, "rejected")}
      />
    </>
  );
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.length ? value.join("、") : "-";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function ReviewSection({ title, children }) {
  return (
    <section style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 12, background: "#fff" }}>
      <h3 style={{ fontSize: "0.95rem", margin: "0 0 10px", color: "#111827" }}>{title}</h3>
      {children}
    </section>
  );
}

function KeyValueGrid({ data }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
      {data.map((item) => (
        <div key={item.label} style={{ background: "#f9fafb", border: "1px solid #eef2f7", borderRadius: 6, padding: 8 }}>
          <div style={{ fontSize: "0.68rem", color: "#6b7280", marginBottom: 4 }}>{item.label}</div>
          <div style={{ fontSize: "0.78rem", color: "#111827", whiteSpace: "pre-wrap" }}>{formatValue(item.value)}</div>
        </div>
      ))}
    </div>
  );
}

function CompactList({ items, getText = (item) => item }) {
  const list = items || [];
  if (!list.length) return <div style={{ fontSize: "0.76rem", color: "#9ca3af" }}>暂无</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {list.slice(0, 12).map((item, index) => (
        <div key={`${index}-${formatValue(getText(item)).slice(0, 20)}`} style={{ fontSize: "0.76rem", color: "#374151", padding: "6px 8px", borderRadius: 6, background: "#f9fafb" }}>
          {formatValue(getText(item))}
        </div>
      ))}
      {list.length > 12 && <div style={{ fontSize: "0.72rem", color: "#6b7280" }}>另有 {list.length - 12} 项未展开</div>}
    </div>
  );
}

function getScoringRows(rubric) {
  if (!rubric) return [];
  if (Array.isArray(rubric.dimensions) && rubric.dimensions.length) return rubric.dimensions;
  if (Array.isArray(rubric.items) && rubric.items.length) {
    return rubric.items.map((item) => ({
      name: item.name || item.dimension || item.key || "评分项",
      max_score: item.max_score,
      key: item.key || item.dimension,
      criteria: item.criteria || [],
    }));
  }
  if (Array.isArray(rubric.criteria) && rubric.criteria.length) {
    return rubric.criteria.map((item) => ({
      name: item.name || item.criterion || item.key || "评分项",
      max_score: item.max_score || item.score,
      key: item.key || item.criterion,
    }));
  }
  return [];
}

function getErrorRows(caseData) {
  const rows = [
    ...(caseData?.severe_errors || []),
    ...(caseData?.dynamic_severe_errors || []),
    ...(caseData?.serious_errors || []),
    ...(caseData?.critical_errors || []),
  ];
  const seen = new Set();
  return rows.filter((item) => {
    const key = typeof item === "object" ? (item.code || item.message || item.reason || JSON.stringify(item)) : String(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function getValidationRows(validation) {
  const rows = [...(validation?.errors || []), ...(validation?.warnings || [])];
  return rows.length ? rows : ["校验通过，未发现错误或警告"];
}

function CaseReviewDetailModal({ detail, comment, onCommentChange, onClose, onApprove, onReject }) {
  const caseData = detail.caseData;
  const validation = caseData?.validation || {};
  const standardAnswer = caseData?.standard_answer || {};
  const timelineEvents = caseData?.dynamic_timeline?.events || [];
  const scoringDimensions = getScoringRows(caseData?.scoring_rubric);
  const severeErrors = getErrorRows(caseData);
  const validationRows = getValidationRows(validation);

  return (
    <Modal open={detail.open} title={caseData ? `病例审核详情：${caseData.display_name || caseData.external_id}` : "病例审核详情"} onClose={onClose} maxWidth={980}>
      {detail.loading && <LoadingState />}
      {!detail.loading && caseData && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: 10, fontSize: "0.78rem", color: "#991b1b" }}>
            审核依据应包括病例结构完整性、患者表现是否清楚、标准分诊答案是否合理、动态时间轴是否闭环、评分规则和严重错误是否可追溯。本系统仅用于护理教育训练，不用于真实临床分诊或诊疗决策。
          </div>

          <ReviewSection title="基础信息">
            <KeyValueGrid data={[
              { label: "病例ID", value: caseData.external_id },
              { label: "类型", value: caseData.case_type === "dynamic" ? "动态病例" : "静态病例" },
              { label: "类别", value: caseData.category },
              { label: "难度", value: caseData.difficulty },
              { label: "目标学员", value: caseData.target_user },
              { label: "训练重点", value: caseData.training_focus },
              { label: "当前审核状态", value: REVIEW_ST[caseData.review?.status] || caseData.review?.status || "draft" },
              { label: "结构校验", value: validation.valid ? "通过" : "未通过" },
            ]} />
          </ReviewSection>

          <ReviewSection title="患者资料与初始场景">
            <KeyValueGrid data={[
              { label: "年龄", value: caseData.patient_profile?.age },
              { label: "性别", value: caseData.patient_profile?.gender },
              { label: "来院方式", value: caseData.patient_profile?.arrival_mode },
              { label: "初始外观", value: caseData.patient_profile?.appearance },
              { label: "特殊身份", value: caseData.patient_profile?.special_identity },
              { label: "主诉", value: caseData.initial_exposure?.chief_complaint },
              { label: "开场表达", value: caseData.initial_exposure?.opening_line },
              { label: "场景描述", value: caseData.initial_exposure?.scene_description },
            ]} />
          </ReviewSection>

          <ReviewSection title="标准答案与处置依据">
            <KeyValueGrid data={[
              { label: "标准分诊等级", value: standardAnswer.triage_level },
              { label: "最低安全等级", value: standardAnswer.minimum_safe_level },
              { label: "标准区域", value: standardAnswer.triage_zone },
              { label: "初始标准等级/区域", value: `${caseData.standard_initial_triage_level || "-"} / ${caseData.standard_initial_area || "-"}` },
              { label: "最终标准等级/区域", value: `${caseData.standard_final_triage_level || "-"} / ${caseData.standard_final_area || "-"}` },
              { label: "复评要求", value: standardAnswer.reassessment_plan },
              { label: "沟通记录要求", value: standardAnswer.communication_and_record },
            ]} />
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: "0.76rem", color: "#6b7280", marginBottom: 6 }}>标准处置</div>
              <CompactList items={standardAnswer.disposition || []} />
            </div>
          </ReviewSection>

          <ReviewSection title="问诊、测量与动态状态">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
              <div>
                <div style={{ fontSize: "0.76rem", color: "#6b7280", marginBottom: 6 }}>关键问诊项（{caseData.required_questions?.length || 0}）</div>
                <CompactList items={caseData.required_questions || []} getText={(q) => q.label || q.id} />
              </div>
              <div>
                <div style={{ fontSize: "0.76rem", color: "#6b7280", marginBottom: 6 }}>生命体征/测量项（{caseData.required_measurements?.length || 0}）</div>
                <CompactList items={caseData.required_measurements || []} getText={(m) => `${m.label || m.id}${m.value ? `：${m.value}` : ""}${m.is_abnormal ? "（异常）" : ""}`} />
              </div>
              <div>
                <div style={{ fontSize: "0.76rem", color: "#6b7280", marginBottom: 6 }}>动态患者状态（{caseData.patient_states?.length || 0}）</div>
                <CompactList items={caseData.patient_states || []} getText={(s) => `T${s.time_minute ?? "-"} ${s.state_name || s.appearance || s.state_id} / ${s.standard_triage_level || "-"}`} />
              </div>
            </div>
          </ReviewSection>

          {caseData.case_type === "dynamic" && (
            <ReviewSection title="病例时间轴">
              <CompactList
                items={timelineEvents}
                getText={(event) => `T${event.scheduled_minute ?? event.time_minute ?? "-"} ${event.event_type || ""}：${event.event_description || ""}；期望操作：${(event.expected_student_actions || []).join("、")}`}
              />
            </ReviewSection>
          )}

          <ReviewSection title="评分规则、严重错误与校验结果">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
              <div>
                <div style={{ fontSize: "0.76rem", color: "#6b7280", marginBottom: 6 }}>评分维度</div>
                <CompactList items={scoringDimensions} getText={(d) => {
                  const criteriaCount = d.criteria?.length ? `，${d.criteria.length}条标准` : "";
                  return `${d.name || d.dimension || d.key || "评分项"}：${d.max_score ?? d.score ?? "-"}分${criteriaCount}`;
                }} />
              </div>
              <div>
                <div style={{ fontSize: "0.76rem", color: "#6b7280", marginBottom: 6 }}>严重错误</div>
                <CompactList items={severeErrors} getText={(e) => e.message || e.reason || e.description || e.code || e} />
              </div>
              <div>
                <div style={{ fontSize: "0.76rem", color: "#6b7280", marginBottom: 6 }}>数据校验</div>
                <CompactList items={validationRows} />
              </div>
            </div>
          </ReviewSection>

          <ReviewSection title="审核意见">
            <textarea
              value={comment}
              onChange={(e) => onCommentChange(e.target.value)}
              placeholder="填写通过或拒绝的理由，例如：标准等级不合理、时间轴缺少T30状态、严重错误项不完整等"
              style={{ width: "100%", minHeight: 80, padding: 10, border: "1px solid #d1d5db", borderRadius: 6, resize: "vertical" }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
              <Button variant="outline" onClick={onClose}>关闭</Button>
              <Button variant="danger" onClick={onReject}>拒绝</Button>
              <Button onClick={onApprove}>通过</Button>
            </div>
          </ReviewSection>
        </div>
      )}
    </Modal>
  );
}

function AnalyticsTab({ stats }) {
  if (!stats?.error_types?.length) return <EmptyState title="暂无错误数据" />;
  const errorData = (stats.error_types || []).slice(0, 10);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: 12 }}>
      <Card title="高频错误类型 Top 10">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={errorData} layout="vertical" margin={{ left: 120 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="code" tick={{ fontSize: 10 }} width={110} />
            <Tooltip />
            <Bar dataKey="count" fill="#dc2626" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <Card title="分诊准确率趋势">
        {stats.recent_trend?.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={stats.recent_trend.slice(-20)}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="avg_score" stroke="#2563eb" name="平均分" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        ) : <EmptyState title="暂无趋势数据" />}
      </Card>
    </div>
  );
}

function ScenariosTab() {
  const [scenarios, setScenarios] = useState([]);
  useEffect(() => { getTriageScenarios().then(r => setScenarios(r.data.items || [])).catch(() => {}); }, []);
  return (
    <div>
      <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: 8, marginBottom: 12, fontSize: "0.72rem", color: "#991b1b" }}>
        ⚠ 仅用于教学训练，不用于真实临床分诊。
      </div>
      {scenarios.map(s => (
        <Card key={s.id} title={s.title} style={{ marginBottom: 8 }}>
          <div style={{ fontSize: "0.78rem", color: "#6b7280" }}>
            <Badge variant={s.scenario_type === "crowding" ? "danger" : "warning"}>{s.scenario_type}</Badge> 难度: {s.difficulty} · 审核: <Badge variant={s.expert_review_status === "approved" ? "success" : "warning"}>{s.expert_review_status}</Badge>
          </div>
          <div style={{ fontSize: "0.75rem", marginTop: 4 }}>{s.description}</div>
        </Card>
      ))}
      {scenarios.length === 0 && <EmptyState title="暂无场景" />}
    </div>
  );
}

function ExportTab({ records, tasks }) {
  const recordPager = usePagination(records || [], 10);
  const taskPager = usePagination(tasks || [], 10);
  const handleCSV = async (taskId = "") => {
    const res = await exportTriageScoresCsv(taskId ? { task_id: taskId } : {});
    const u = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = u;
    a.download = taskId ? `triage_task_${taskId}.csv` : "triage_scores.csv";
    a.click();
    URL.revokeObjectURL(u);
  };
  const handlePrintHTML = (recordId) => { window.open(`/api/triage/export/record/${recordId}/html`, "_blank"); };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Card title="导出训练记录">
        <div style={{ display: "flex", gap: 8 }}>
          <Button onClick={() => handleCSV()}>导出成绩 CSV</Button>
          <Button variant="outline" onClick={() => window.open("/api/triage/export/all", "_blank")}>API JSON 导出</Button>
        </div>
      </Card>
      <Card title="可打印HTML报告">
        {recordPager.pageItems.map(r => (
          <div key={r.id} style={{ padding: "4px 0", display: "flex", justifyContent: "space-between", fontSize: "0.78rem" }}>
            <span>{r.user_display_name} — {r.case_external_id} ({r.total_score}分)</span>
            <Button size="sm" variant="outline" onClick={() => handlePrintHTML(r.id)}>打印HTML</Button>
          </div>
        ))}
        {records.length === 0 && <EmptyState title="暂无可打印记录" />}
        <PaginationControls
          page={recordPager.page}
          pageSize={recordPager.pageSize}
          total={recordPager.total}
          pageCount={recordPager.pageCount}
          onPageChange={recordPager.setPage}
          onPageSizeChange={recordPager.setPageSize}
        />
      </Card>
      <Card title="考核任务成绩">
        {taskPager.pageItems.map(t => (
          <div key={t.id} style={{ padding: "6px 0", borderBottom: "1px solid #eee", fontSize: "0.8rem" }}>
            <b>{t.title}</b> <Badge variant={t.mode === "exam" ? "danger" : t.mode === "osce" ? "warning" : "info"}>{MODES[t.mode]}</Badge>
            {" "}— {(t.assignments || []).filter(a => a.status === "scored").length}/{(t.assignments || []).length} 完成
            <Button size="sm" variant="outline" style={{ marginLeft: 8 }} onClick={() => handleCSV(t.id)}>导出本任务</Button>
            {t.mode === "exam" && <span style={{ color: "#dc2626", fontSize: "0.7rem", marginLeft: 8 }}>⚠ 考核模式：提交后不可修改，限时{t.time_limit_minutes || 8}分钟</span>}
          </div>
        ))}
        {tasks.length === 0 && <EmptyState title="暂无考核任务" />}
        <PaginationControls
          page={taskPager.page}
          pageSize={taskPager.pageSize}
          total={taskPager.total}
          pageCount={taskPager.pageCount}
          onPageChange={taskPager.setPage}
          onPageSizeChange={taskPager.setPageSize}
        />
      </Card>
    </div>
  );
}
