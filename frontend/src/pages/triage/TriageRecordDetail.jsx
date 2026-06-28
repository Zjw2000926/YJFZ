import { useState, useEffect } from "react";
import { useParams, useLocation } from "react-router-dom";
import { getTriageRecord, submitTeacherReview } from "../../api";
import Layout from "../../components/Layout";
import PageHeader from "../../components/ui/PageHeader";
import Card from "../../components/ui/Card";
import Badge from "../../components/ui/Badge";
import LoadingState from "../../components/ui/LoadingState";
import { useToast } from "../../components/useToast";
import { ClipboardList, AlertTriangle, CheckCircle } from "lucide-react";
import ScoreBreakdownDetails from "../../components/triage/ScoreBreakdownDetails";

const PASS_LABELS = { excellent: "优秀", good: "良好", pass: "合格", fail: "不合格" };
const PASS_COLORS = { excellent: "success", good: "info", pass: "warning", fail: "danger" };

const toArray = (v) => Array.isArray(v) ? v : (v ? [v] : []);

export default function TriageRecordDetail({ user, onLogout }) {
  const { id } = useParams();
  const location = useLocation();
  const toast = useToast();
  const [record, setRecord] = useState(null);
  const [score, setScore] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [teacherScore, setTeacherScore] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [reviewing, setReviewing] = useState(false);

  const navScore = location.state?.score;
  const navRecord = location.state?.record;

  useEffect(() => {
    // 优先使用导航状态中的数据
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (navScore) setScore(navScore);
    if (navRecord) setRecord(navRecord);

    setLoadError("");
    getTriageRecord(id).then(({ data }) => {
      const rec = data.record;
      setRecord(rec);
      // 使用 != null 同时匹配 null 和 undefined
      if (rec?.total_score != null && rec?.score_detail) {
        // 从 record 恢复完整评分数据
        setScore({
          total_score: rec.total_score,
          pass_status: rec.pass_status,
          severe_error_triggered: rec.severe_error_triggered,
          severe_errors: rec.severe_error_codes || [],
          detail_scores: rec.score_detail,
          score_explanations: rec.score_explanations || [],
          criterion_scores: rec.criterion_scores || [],
          rule_result: rec.rule_result || null,
          standard_answer: rec.standard_answer || null,
          timeline_report: rec.timeline_report || null,
          core_scores: rec.core_scores || null,
          complex_scores: rec.complex_scores || null,
          feedback: rec.feedback,
          effective_score: rec.effective_score,
        });
      } else if (!navScore) {
        setScore(null);
      }
    }).catch((err) => {
      const message = err.response?.data?.detail || "加载记录失败，请确认该报告未被删除且当前账号有权限查看。";
      setLoadError(typeof message === "string" ? message : message?.message || "加载记录失败");
      toast.error("加载记录失败");
    })
      .finally(() => setLoading(false));
  }, [id, navScore, navRecord, toast]);

  const feedback = score?.feedback || {};
  const riskItems = toArray(feedback.risk_if_missed);
  const redFlagItems = toArray(feedback.key_red_flag);
  const feedbackEvidence = feedback.feedback_evidence || {};
  const feedbackEvidenceItems = toArray(feedbackEvidence.covered_items);
  const feedbackEvidenceBasis = feedbackEvidence.basis || "";
  const missedItems = [
    ...toArray(feedback.missed_required_questions),
    ...toArray(feedback.missed_measurements),
    ...toArray(feedback.missed_red_flags),
    ...toArray(feedback.missed_content),
  ];
  const remediation = toArray(feedback.recommended_remediation).length > 0
    ? toArray(feedback.recommended_remediation)
    : toArray(feedback.next_practice_focus);
  const isExamMode = record?.mode === "exam" || record?.mode === "osce";
  const isEducator = ["teacher", "reviewer", "admin"].includes(user?.role);
  const scoreReleased = !isExamMode || Boolean(record?.score_released || record?.show_feedback_immediately);
  const feedbackReleased = !isExamMode || Boolean(record?.show_feedback_immediately);
  const standardAnswerReleased = !isExamMode || Boolean(record?.show_standard_answer);
  const canSeeScore = scoreReleased || isEducator;
  const canSeeDetailedFeedback = feedbackReleased || isEducator;
  const canSeeStandardAnswer = standardAnswerReleased || isEducator;
  const hasHiddenExamContent = isExamMode && !isEducator && score && (
    !canSeeScore || !canSeeDetailedFeedback || (score?.standard_answer && !canSeeStandardAnswer)
  );
  const canReview = ["teacher", "admin"].includes(user?.role) && Boolean(score);
  const timelineReport = score?.timeline_report || {};
  const isDynamicReport = Boolean(timelineReport.is_dynamic_case);
  const showReassessmentStatus = timelineReport.reassessment_applicable === true;
  const showDeteriorationStatus = timelineReport.deterioration_applicable === true;
  const showUpgradeStatus = timelineReport.upgrade_applicable === true;
  const showDoctorStatus = timelineReport.doctor_notification_required === true;

  const handleTeacherReview = async () => {
    const value = Number(teacherScore);
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      toast.error("请输入 0-100 的复核分数");
      return;
    }
    setReviewing(true);
    try {
      const { data } = await submitTeacherReview(id, {
        teacher_score: value,
        comment: reviewComment,
      });
      setRecord((prev) => prev ? {
        ...prev,
        effective_score: data.final_score,
        teacher_review: data.review,
      } : prev);
      toast.success("教师复核已保存");
    } catch (err) {
      toast.error(err.response?.data?.detail || "保存复核失败");
    } finally {
      setReviewing(false);
    }
  };

  if (loading) return <Layout user={user} onLogout={onLogout}><LoadingState /></Layout>;
  if (!record) return (
    <Layout user={user} onLogout={onLogout}>
      <PageHeader
        title="预检分诊报告"
        subtitle={`记录：${id}`}
        icon={ClipboardList}
        backTo={isEducator ? "/triage/admin" : "/triage/tasks"}
      />
      <Card>
        <div style={{ padding: 24, textAlign: "center" }}>
          <AlertTriangle size={32} color="#dc2626" />
          <div style={{ fontWeight: 700, marginTop: 10 }}>报告无法打开</div>
          <div style={{ color: "#6b7280", fontSize: "0.85rem", marginTop: 6 }}>{loadError || "记录不存在或已被删除。"}</div>
        </div>
      </Card>
    </Layout>
  );

  return (
    <Layout user={user} onLogout={onLogout}>
      <PageHeader
        title="预检分诊报告"
        subtitle={`病例：${record.case_external_id}`}
        icon={ClipboardList}
        backTo={isEducator ? "/triage/admin" : "/triage/tasks"}
      />

      <div style={{ marginBottom: 16, padding: 10, border: "1px solid #dbeafe", background: "#eff6ff", borderRadius: 8, fontSize: "0.78rem", color: "#1e40af" }}>
        本系统仅用于护理教育训练，不用于真实临床分诊或诊疗决策。
      </div>

      {/* 总分概览 */}
      {score && canSeeScore && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
          <Card>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "2rem", fontWeight: 800, color: score.total_score >= 80 ? "#16a34a" : score.total_score >= 60 ? "#d97706" : "#dc2626" }}>
                {score.total_score}
              </div>
              <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>总分 / 100</div>
              {(score.effective_score != null && score.effective_score !== score.total_score) && <div style={{ fontSize: "0.65rem", color: "#dc2626", marginTop: 2 }}>有效成绩: {score.effective_score} (一票否决封顶59)</div>}
            </div>
          </Card>
          <Card>
            <div style={{ textAlign: "center" }}>
              <Badge variant={PASS_COLORS[score.pass_status] || "neutral"}>{PASS_LABELS[score.pass_status] || score.pass_status}</Badge>
              <div style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: 4 }}>评级</div>
            </div>
          </Card>
          <Card>
            <div style={{ textAlign: "center" }}>
              {record.final_level_selected ? (
                <span style={{ fontSize: "1.2rem", fontWeight: 700 }}>{record.final_level_selected}</span>
              ) : <span style={{ color: "#9ca3af" }}>—</span>}
              <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>你的分诊等级</div>
            </div>
          </Card>
          <Card>
            <div style={{ textAlign: "center" }}>
              {score.severe_error_triggered ? (
                <AlertTriangle size={28} color="#dc2626" />
              ) : (
                <CheckCircle size={28} color="#16a34a" />
              )}
              <div style={{ fontSize: "0.75rem", color: score.severe_error_triggered ? "#dc2626" : "#16a34a" }}>
                {score.severe_error_triggered ? "严重错误" : "无严重错误"}
              </div>
            </div>
          </Card>
        </div>
      )}

      {canReview && (
        <Card title="教师复核" style={{ marginBottom: 16 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12, marginBottom: 12, fontSize: "0.82rem" }}>
            <div>
              <div style={{ color: "#6b7280" }}>系统评分</div>
              <div style={{ fontSize: "1.2rem", fontWeight: 800 }}>{score.total_score ?? "—"}</div>
            </div>
            <div>
              <div style={{ color: "#6b7280" }}>复核评分</div>
              <div style={{ fontSize: "1.2rem", fontWeight: 800 }}>{record.teacher_review?.teacher_score ?? "待复核"}</div>
            </div>
            <div>
              <div style={{ color: "#6b7280" }}>最终成绩</div>
              <div style={{ fontSize: "1.2rem", fontWeight: 800 }}>{record.teacher_review?.final_score ?? record.effective_score ?? score.total_score ?? "—"}</div>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "160px 1fr auto", gap: 10, alignItems: "start" }}>
            <input
              type="number"
              min="0"
              max="100"
              value={teacherScore}
              onChange={(e) => setTeacherScore(e.target.value)}
              placeholder="0-100"
              style={{ padding: "9px 10px", border: "1px solid #d1d5db", borderRadius: 6 }}
            />
            <textarea
              value={reviewComment}
              onChange={(e) => setReviewComment(e.target.value)}
              placeholder="填写复核意见"
              rows={2}
              style={{ padding: "9px 10px", border: "1px solid #d1d5db", borderRadius: 6, resize: "vertical" }}
            />
            <button
              type="button"
              className="btn btn-primary"
              disabled={reviewing}
              onClick={handleTeacherReview}
            >
              {reviewing ? "保存中..." : "保存复核"}
            </button>
          </div>
        </Card>
      )}

      {/* 分诊对比 */}
      {score?.standard_answer && canSeeStandardAnswer && (
        <Card title="分诊决策对比" style={{ marginBottom: 16 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, fontSize: "0.85rem" }}>
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>你的决策</div>
              <div>等级：{record.final_level_selected || "未选择"}</div>
              <div>区域：{record.final_zone_selected || "未选择"}</div>
              <div>处置：{(record.final_disposition || []).join("、") || "未选择"}</div>
            </div>
            <div style={{ borderLeft: "1px solid #e5e7eb", paddingLeft: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>标准答案</div>
              <div>等级：{score.standard_answer.triage_level || "—"}</div>
              <div>区域：{score.standard_answer.triage_zone || "—"}</div>
              <div>处置：{(score.standard_answer.disposition || []).join("、") || "—"}</div>
            </div>
          </div>
        </Card>
      )}

      {/* 动态时间线报告 */}
      {score?.timeline_report?.timeline_nodes?.length > 0 && canSeeDetailedFeedback && (
        <Card title={isDynamicReport ? "患者状态时间线" : "训练流程概览"} style={{ marginBottom: 16 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12, fontSize: "0.8rem" }}>
            <div style={{ padding: 8, background: "#f8fafc", borderRadius: 6 }}>
              <div style={{ fontWeight: 600, color: "#2563eb", marginBottom: 4 }}>初始分诊</div>
              <div>标准: {score.timeline_report.standard_initial_level} / {score.timeline_report.standard_initial_area}</div>
              <div>学员: {score.timeline_report.student_initial_level} / {score.timeline_report.student_initial_area}</div>
            </div>
            <div style={{ padding: 8, background: "#f8fafc", borderRadius: 6 }}>
              <div style={{ fontWeight: 600, color: "#dc2626", marginBottom: 4 }}>最终分诊</div>
              <div>标准: {score.timeline_report.standard_final_level} / {score.timeline_report.standard_final_area}</div>
              <div>学员: {score.timeline_report.student_final_level} / {score.timeline_report.student_final_area}</div>
            </div>
          </div>
          {score.timeline_report.timeline_nodes.map((node, i) => (
            <div key={i} style={{ display: "flex", gap: 8, padding: "6px 0", borderBottom: "1px solid #f3f4f6", fontSize: "0.75rem" }}>
              <span style={{ fontWeight: 600, color: "#6b7280", minWidth: 60 }}>{node.label}</span>
              <span style={{ flex: 1 }}>{node.event}</span>
              <span style={{ color: node.had_reassessment ? "#16a34a" : "#9ca3af", fontSize: "0.7rem" }}>
                {node.student_action}
              </span>
            </div>
          ))}
          {!isDynamicReport && (
            <div style={{ marginTop: 10, padding: 8, background: "#f8fafc", borderRadius: 6, color: "#475569", fontSize: "0.72rem" }}>
              本病例为静态立即分诊病例，不要求候诊复评、病情变化识别或升级分诊；请重点复盘初始等级、区域安排、通知医生和安全处置。
            </div>
          )}
          <div style={{ marginTop: 10, display: "flex", gap: 16, fontSize: "0.72rem", flexWrap: "wrap" }}>
            {showReassessmentStatus && (
              <span style={{ color: score.timeline_report.reassessment_on_time ? "#16a34a" : "#dc2626" }}>
                {score.timeline_report.reassessment_on_time ? "✓ 按时复评" : "✗ 未按时复评"}
              </span>
            )}
            {showDeteriorationStatus && (
              <span style={{ color: score.timeline_report.deterioration_recognized ? "#16a34a" : "#dc2626" }}>
                {score.timeline_report.deterioration_recognized ? "✓ 识别病情变化" : "✗ 未识别病情变化"}
              </span>
            )}
            {showUpgradeStatus && (
              <span style={{ color: score.timeline_report.triage_upgraded ? "#16a34a" : "#d97706" }}>
                {score.timeline_report.triage_upgraded ? "✓ 已升级分诊" : "⚠ 未升级分诊"}
              </span>
            )}
            {showDoctorStatus && (
              <span style={{ color: score.timeline_report.doctor_notified ? "#16a34a" : "#dc2626" }}>
                {score.timeline_report.doctor_notified ? "✓ 已通知医生" : "✗ 未通知医生"}
              </span>
            )}
          </div>
        </Card>
      )}

      {/* 生命体征测量记录 */}
      {(score?.timeline_report?.vital_measurement_log || []).length > 0 && canSeeDetailedFeedback && (
        <Card title="生命体征测量记录" style={{ marginBottom: 16 }}>
          {score.timeline_report.vital_measurement_log.map((log, i) => (
            <div key={i} style={{ fontSize: "0.72rem", padding: "4px 0", borderBottom: "1px solid #f3f4f6" }}>
              <span style={{ fontWeight: 600 }}>T{log.simulation_minute}分钟: </span>
              {Object.entries(log.result || {}).map(([k, v]) => (
                <span key={k} style={{ marginRight: 8, color: "#374151" }}>{k}: {String(v)}</span>
              ))}
            </div>
          ))}
        </Card>
      )}

      {/* 评分详情 */}
      {score?.detail_scores && canSeeDetailedFeedback && (
        <Card title="分项评分" style={{ marginBottom: 16 }}>
          <ScoreBreakdownDetails
            detailScores={score.detail_scores}
            showStandardBasis={canSeeStandardAnswer || isEducator}
          />
        </Card>
      )}

{/* 评分证据明细 */}
      {(score?.criterion_scores || []).length > 0 && canSeeDetailedFeedback && (
        <Card title="评分证据明细" style={{ marginBottom: 16 }}>
          {(score.criterion_scores || []).slice(0, 20).map((cs, i) => (
            <div key={i} style={{ padding: "6px 0", borderBottom: "1px solid #f3f4f6", fontSize: "0.75rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span>{cs.criterion || cs.dimension || "评分项"}</span>
                <span style={{ fontWeight: 600, color: (cs.met || cs.score >= (cs.max_score||3)*0.6) ? "#16a34a" : "#dc2626" }}>
                  {cs.score}/{cs.max_score || "?"}
                  {cs.critical_fail && <Badge variant="danger" style={{ marginLeft: 4, fontSize: "0.6rem" }}>严重</Badge>}
                </span>
              </div>
              {!cs.met && cs.missed_reason && <div style={{ color: "#dc2626", fontSize: "0.68rem" }}>原因: {cs.missed_reason}</div>}
              {cs.teaching_point && <div style={{ color: "#2563eb", fontSize: "0.68rem" }}>教学点: {cs.teaching_point}</div>}
            </div>
          ))}
        </Card>
      )}

      {/* 反馈 — P0-G: 专家反馈区 */}
      {score?.feedback && canSeeDetailedFeedback && (
        <Card title="专家反馈" style={{ marginBottom: 16 }}>
          {(toArray(score.feedback.correct_points).length > 0 || toArray(score.feedback.strengths).length > 0) && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: "0.8rem", color: "#16a34a", marginBottom: 4 }}>✓ 正确点</div>
              {(toArray(score.feedback.correct_points).length > 0 ? toArray(score.feedback.correct_points) : toArray(score.feedback.strengths))
                .map((s, i) => <div key={i} style={{ fontSize: "0.75rem", padding: "1px 0" }}>· {s}</div>)}
            </div>
          )}
          {score.feedback.reason_for_triage_level && (
            <div style={{ marginBottom: 10, padding: 8, background: "#eff6ff", borderRadius: 6, fontSize: "0.75rem" }}>
              <b>正确分诊依据：</b>{score.feedback.reason_for_triage_level}
            </div>
          )}
          {riskItems.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: "0.8rem", color: "#dc2626" }}>⚠ 漏掉后风险</div>
              {riskItems.map((r, i) => <div key={i} style={{ fontSize: "0.75rem", color: "#991b1b" }}>· {r}</div>)}
            </div>
          )}
          {redFlagItems.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: "0.8rem", color: "#dc2626" }}>🚩 关键高危信号</div>
              {redFlagItems.map((r, i) => <div key={i} style={{ fontSize: "0.75rem" }}>· {r}</div>)}
            </div>
          )}
          {(feedbackEvidenceBasis || feedbackEvidenceItems.length > 0) && (
            <div style={{ marginBottom: 10, padding: 8, background: "#f8fafc", border: "1px solid #e5e7eb", borderRadius: 6, fontSize: "0.75rem", color: "#374151" }}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>反馈依据</div>
              {feedbackEvidenceBasis && <div style={{ marginBottom: 4 }}>{feedbackEvidenceBasis}</div>}
              {feedbackEvidenceItems.length > 0 && (
                <div>已从记录中识别：{feedbackEvidenceItems.slice(0, 12).join("、")}</div>
              )}
            </div>
          )}
          {missedItems.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: "0.8rem", color: "#d97706" }}>✗ 遗漏项</div>
              {missedItems.slice(0, 8).map((m, i) => <div key={i} style={{ fontSize: "0.75rem" }}>· {m}</div>)}
            </div>
          )}
          {remediation.length > 0 && (

            <div style={{ padding: 8, background: "#f0fdf4", borderRadius: 6, fontSize: "0.78rem" }}>
              <b>📝 补训建议：</b>{remediation.join("；")}
            </div>
          )}
          {score.feedback.safety_critical_errors?.length > 0 && (
            <div style={{ marginTop: 8, padding: 8, background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 6 }}>
              <div style={{ fontWeight: 700, fontSize: "0.8rem", color: "#dc2626" }}>⛔ 安全关键错误 (一票否决)</div>
              {score.feedback.safety_critical_errors.map((e, i) => <div key={i} style={{ fontSize: "0.75rem", color: "#991b1b" }}>· {e}</div>)}
            </div>
          )}
        </Card>
      )}
      {hasHiddenExamContent && (
        <Card title="考核结果开放状态">
          <p style={{fontSize:"0.85rem",color:"#6b7280", marginBottom: 8}}>
            本次为考核模式，系统已记录提交结果。教师可在任务管理中发布成绩、详细反馈和标准答案。
          </p>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", fontSize: "0.76rem" }}>
            <Badge variant={canSeeScore ? "success" : "neutral"}>{canSeeScore ? "成绩已开放" : "成绩待教师发布"}</Badge>
            <Badge variant={canSeeDetailedFeedback ? "success" : "neutral"}>{canSeeDetailedFeedback ? "详细反馈已开放" : "详细反馈待教师发布"}</Badge>
            <Badge variant={canSeeStandardAnswer ? "success" : "neutral"}>{canSeeStandardAnswer ? "标准答案已开放" : "标准答案待教师发布"}</Badge>
          </div>
        </Card>
      )}

      {/* 对话记录 */}
      {record.messages?.length > 0 && (
        <Card title="训练对话记录">
          <div style={{ maxHeight: 400, overflow: "auto" }}>
            {record.messages.map((msg, i) => (
              <div key={i} style={{ padding: "6px 10px", margin: "4px 0", borderRadius: 6, background: msg.role === "student" ? "#eff6ff" : "#f0fdf4", fontSize: "0.8rem" }}>
                <span style={{ fontWeight: 600, color: msg.role === "student" ? "#2563eb" : "#16a34a", marginRight: 8 }}>
                  {msg.role === "student" ? "你" : "患者"}
                </span>
                {msg.content}
              </div>
            ))}
          </div>
        </Card>
      )}
    </Layout>
  );
}
