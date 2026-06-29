import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, User, Send, Clock, Activity, AlertTriangle, Phone, Target, Eye } from "lucide-react";
import {
  startTriageTraining,
  sendTriageMessage,
  measureTriageVitals,
  submitTriage,
  getTriageCaseDetail,
  observeTriagePatient,
  getTriageRecord,
  getTriageState,
  recordInitialDecision,
  submitFollowUpDecision,
} from "../../api";
import { useToast } from "../../components/useToast";
import { useConfirm } from "../../components/ui/useConfirm";
import { calculateTimeLeftSeconds, formatCountdownTime, getPositiveInt, getTrainingTimerEndMs } from "../../utils/trainingTimer";
import TriageFollowUpDecisionPanel from "../../components/triage/TriageFollowUpDecisionPanel";

const LEVELS = [
  { value: "Ⅰ级", label: "Ⅰ级(濒危)", color: "#dc2626", desc: "立即抢救" },
  { value: "Ⅱ级", label: "Ⅱ级(危重)", color: "#ea580c", desc: "10分钟内处理" },
  { value: "Ⅲ级", label: "Ⅲ级(急症)", color: "#ca8a04", desc: "30分钟内处理" },
  { value: "Ⅳ级", label: "Ⅳ级(非急症)", color: "#16a34a", desc: "可候诊" },
];
const ZONES = [
  { value: "红区", label: "红区", color: "#dc2626", desc: "抢救区/监护区" },
  { value: "黄区", label: "黄区", color: "#d97706", desc: "观察区" },
  { value: "绿区", label: "绿区", color: "#16a34a", desc: "普通候诊区" },
];
const DISPOSITIONS = ["通知医生", "绿色通道", "立即处理", "心电监护", "吸氧", "建立静脉通路", "普通候诊", "建议门诊"];

export default function TriageTraining() {
  const [searchParams] = useSearchParams();
  const caseId = searchParams.get("case");
  const mode = searchParams.get("mode") || "practice";
  const isExam = mode === "exam" || mode === "osce";
  const navigate = useNavigate();
  const { success, error, warning } = useToast();
  const { confirm } = useConfirm();
  const startedRef = useRef(false);
  const timerEndsAtRef = useRef(null);

  const [recordId, setRecordId] = useState(null);
  const [caseData, setCaseData] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [vitals, setVitals] = useState(null);
  const [askedCount, setAskedCount] = useState(0);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [disclosedSlots, setDisclosedSlots] = useState([]);
  const [selectedLevel, setSelectedLevel] = useState(null);
  const [selectedZone, setSelectedZone] = useState(null);
  const [selectedDispositions, setSelectedDispositions] = useState([]);
  const [triageReason, setTriageReason] = useState("");
  const [handoffNote, setHandoffNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [initialDecisionRecorded, setInitialDecisionRecorded] = useState(false);
  const [followUpOption, setFollowUpOption] = useState("");
  const [followUpDecisionRecorded, setFollowUpDecisionRecorded] = useState(false);
  const [followUpDecisionResult, setFollowUpDecisionResult] = useState(null);
  const [followUpStateUpdates, setFollowUpStateUpdates] = useState([]);
  const taskIdParam = searchParams.get("task_id");
  const timeLimitParam = searchParams.get("time_limit");
  const recordIdParam = searchParams.get("record_id");
  const initialTimeLimitSeconds = (getPositiveInt(timeLimitParam) || 8) * 60;
  const [timeLeft, setTimeLeft] = useState(initialTimeLimitSeconds);
  const [timerStarted, setTimerStarted] = useState(false);
  const [observed, setObserved] = useState([]);
  const [selectedObs, setSelectedObs] = useState([]);
  const [selectedMeasureIds, setSelectedMeasureIds] = useState([]);
  const obsOptions = caseData?.observation_options || [];
  const measOptions = caseData?.measurement_options || [];

  const syncTimerFromRecord = useCallback((record, fallbackLimitMinutes) => {
    const limitMinutes = getPositiveInt(record?.time_limit_minutes) || getPositiveInt(fallbackLimitMinutes) || 8;
    timerEndsAtRef.current = getTrainingTimerEndMs(record, fallbackLimitMinutes);
    setTimeLeft(calculateTimeLeftSeconds(record?.started_at, limitMinutes));
  }, []);

  const toggleObs = (id) => { setSelectedObs(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]); };
  const toggleMeasure = (id) => { setSelectedMeasureIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]); };

  const handleObserve = async () => {
    if (obsOptions.length > 0 && selectedObs.length === 0) {
      warning("请至少选择一项观察内容"); return;
    }
    try {
      const ids = obsOptions.length > 0 ? selectedObs : [];
      const { data } = await observeTriagePatient(recordId, ids);
      // 合并观察结果，不覆盖已有记录
      setObserved((prev) => {
        const map = new Map(prev.map((item) => [item.id, item]));
        (data.observations || []).forEach((item) => map.set(item.id, item));
        return Array.from(map.values());
      });
      success("观察已记录");
    } catch { error("观察记录失败"); }
  };

  const messagesEndRef = useRef(null);

  // 初始化：加载病例详情
  useEffect(() => {
    if (!caseId) return;
    getTriageCaseDetail(caseId).then(({ data }) => {
      setCaseData(data.case);
      setTotalQuestions(data.case?.required_questions?.length || 0);
    }).catch(() => { error("加载病例失败"); navigate("/triage"); });
  }, [caseId, error, navigate]);

  // 初始化：创建训练记录（一次性，不因观察/测量重新执行）
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const timeLimitVal = getPositiveInt(timeLimitParam);
    if (recordIdParam) {
      Promise.all([
        getTriageRecord(recordIdParam),
        getTriageState(recordIdParam).catch(() => ({ data: {} })),
      ]).then(([recordRes, stateRes]) => {
        const record = recordRes.data.record;
        if (!record || record.status !== "in_progress") {
          navigate(`/triage/record/${recordIdParam}`, { replace: true });
          return;
        }
        setRecordId(record.id);
        setMessages(record.messages?.length ? record.messages.map((m) => ({ role: m.role, content: m.content })) : []);
        setSubmitted(false);
        setDisclosedSlots(stateRes.data.disclosed_slots || []);
        setAskedCount((stateRes.data.disclosed_slots || []).length);
        setObserved(stateRes.data.observed_details || []);
        setInitialDecisionRecorded(Boolean((record.triage_decisions || []).some((item) => item.decision_type === "initial")));
        const restoredFollowUps = record.follow_up_decisions || [];
        setFollowUpDecisionRecorded(restoredFollowUps.length > 0);
        if (restoredFollowUps.length > 0) setFollowUpDecisionResult(restoredFollowUps[restoredFollowUps.length - 1]);
        syncTimerFromRecord(record, timeLimitVal);
        setTimerStarted(true);
        const recordCaseId = record.case_external_id;
        if (!caseData && recordCaseId && recordCaseId !== caseId) {
          getTriageCaseDetail(recordCaseId).then(({ data }) => {
            setCaseData(data.case);
            setTotalQuestions(data.case?.required_questions?.length || 0);
          }).catch(() => {});
        }
      }).catch((err) => { error(err?.response?.data?.detail || "恢复训练失败"); navigate("/triage/tasks"); })
        .finally(() => setLoading(false));
      return;
    }

    if (!caseId) { navigate("/triage"); return; }
    startTriageTraining(caseId, "default", { mode, timeLimitMinutes: timeLimitVal, taskId: taskIdParam }).then(({ data }) => {
      setRecordId(data.record_id);
      setMessages([{ role: "patient", content: data.opening_line }]);
      syncTimerFromRecord(data, timeLimitVal);
      const params = new URLSearchParams(window.location.search);
      params.set("record_id", data.record_id);
      navigate(`/triage/training/start?${params.toString()}`, { replace: true });
      setTimerStarted(true);
    }).catch((err) => { error(err?.response?.data?.detail || "创建训练失败"); navigate("/triage"); })
      .finally(() => setLoading(false));
  }, [caseData, caseId, mode, recordIdParam, syncTimerFromRecord, taskIdParam, timeLimitParam, error, navigate]);

  // 倒计时
  useEffect(() => {
    if (!timerStarted || submitted) return;
    const timer = setInterval(() => {
      if (timerEndsAtRef.current) {
        const remaining = Math.max(0, Math.ceil((timerEndsAtRef.current - Date.now()) / 1000));
        setTimeLeft(remaining);
        if (remaining === 0) setTimerStarted(false);
        return;
      }
      setTimeLeft((t) => { if (t <= 1) { setTimerStarted(false); return 0; } return t - 1; });
    }, 1000);
    return () => clearInterval(timer);
  }, [timerStarted, submitted]);

  // 滚动
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // 发送消息
  const handleSend = async () => {
    const content = input.trim();
    if (!content || sending || submitted) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "student", content }]);
    setSending(true);
    try {
      const { data } = await sendTriageMessage(recordId, content);
      setMessages((prev) => [...prev, { role: "patient", content: data.reply }]);
      // V2: capture disclosed slots + intents
      if (data.disclosed_slots) setDisclosedSlots(data.disclosed_slots);
      if (data.asked_count !== undefined) setAskedCount(data.asked_count);
      else if (data.disclosed_slots) setAskedCount(data.disclosed_slots.length);
    } catch { error("发送失败"); }
    finally { setSending(false); }
  };

  // 测量生命体征
  const handleMeasure = async (ids = null) => {
    try {
      const mids = ids || (measOptions.length > 0 ? selectedMeasureIds : []);
      if (measOptions.length > 0 && mids.length === 0) {
        warning("请选择要测量的项目"); return;
      }
      const { data } = await measureTriageVitals(recordId, mids);
      const results = data.measurements || [];
      setVitals(results);
      success("测量完成");
    } catch { error("测量失败"); }
  };

  const handleInitialDecision = async () => {
    if (!selectedLevel) { warning("请选择分诊等级"); return; }
    if (!selectedZone) { warning("请选择就诊区域"); return; }
    try {
      await recordInitialDecision(recordId, {
        level: selectedLevel,
        zone: selectedZone,
        notify_doctor: selectedDispositions.includes("通知医生"),
        reason: triageReason,
      });
      setInitialDecisionRecorded(true);
      setFollowUpDecisionRecorded(false);
      setFollowUpDecisionResult(null);
      success("初始分诊已记录，请继续判断候诊与复评策略");
    } catch (err) {
      error(err?.response?.data?.detail || "记录初始分诊失败");
    }
  };

  const handleFollowUpDecision = async () => {
    if (!initialDecisionRecorded) { warning("请先记录初始分诊"); return; }
    if (!followUpOption) { warning("请选择后续管理策略"); return; }
    try {
      const { data } = await submitFollowUpDecision(recordId, {
        selected_option: followUpOption,
        case_stage: "after_initial_triage",
        reason: triageReason || handoffNote,
      });
      const decision = data.decision || {};
      setFollowUpDecisionResult(decision);
      if (followUpOption === "upgrade_notify_doctor" && !selectedDispositions.includes("通知医生")) {
        setSelectedDispositions((prev) => [...prev, "通知医生"]);
      }
      if (data.state_update) {
        setFollowUpStateUpdates((prev) => [...prev, data.state_update]);
        setFollowUpOption("");
        setFollowUpDecisionRecorded(false);
        success("已进入候诊观察结果，请继续判断下一步处理");
      } else {
        setFollowUpDecisionRecorded(true);
        success("后续管理决策已记录");
      }
    } catch (err) {
      error(err?.response?.data?.detail || "记录后续管理决策失败");
    }
  };

  // 提交
  const handleSubmit = async () => {
    if (!selectedLevel) { warning("请选择分诊等级"); return; }
    if (!selectedZone) { warning("请选择就诊区域"); return; }
    if (!initialDecisionRecorded) { warning("请先记录初始分诊决策"); return; }
    if (!followUpDecisionRecorded) { warning("请先完成候诊与复评决策"); return; }
    const ok = await confirm({ title: "提交分诊", message: "确定提交分诊决策吗？提交后将自动评分。", confirmLabel: "确定提交", danger: true });
    if (!ok) return;
    try {
      const { data } = await submitTriage(recordId, {
        level: selectedLevel,
        zone: selectedZone,
        disposition: selectedDispositions,
        reason: triageReason,
        note: handoffNote,
      });
      if (data?.score?.total_score == null) {
        error("提交成功但评分结果为空，请联系教师或重试");
        return;
      }
      setSubmitted(true);
      navigate(`/triage/record/${recordId}`, { state: { score: data.score, record: data.record } });
    } catch { error("提交失败"); }
  };


  if (loading) return <div style={{ padding: 40, textAlign: "center" }}>加载中...</div>;

  return (
    <div className="training-shell">
      {/* 顶部栏 */}
      <header className="training-topbar">
        <button className="training-back" onClick={() => navigate("/triage")}><ArrowLeft size={20} /></button>
        <div className="training-patient-identity">
          <div className="training-patient-avatar"><User size={20} /></div>
          <div>
            <div className="training-patient-name">{caseData?.patient_profile?.arrival_mode || "患者"}</div>
            <div className="training-patient-desc">{caseData?.display_name || ""} · {isExam ? <span style={{color:"#dc2626",fontWeight:600}}>考核模式</span> : sending ? "输入中..." : "在线"}</div>
          </div>
        </div>
        <div className="training-timer" style={timeLeft <= 120 ? { background: "#fef2f2", borderColor: "#fca5a5", color: "#dc2626" } : {}}>
          <Clock size={16} /><span>{formatCountdownTime(timeLeft)}</span>
        </div>
        {submitted ? (
          <span style={{ color: "#16a34a", fontWeight: 600, fontSize: "0.85rem" }}>已提交</span>
        ) : (
          <button className="training-end-btn" onClick={handleSubmit} disabled={!selectedLevel || !selectedZone || !initialDecisionRecorded || !followUpDecisionRecorded}>
            <Phone size={16} /><span>提交分诊</span>
          </button>
        )}
      </header>

      {/* 主体：对话区 + 决策面板 */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* 左侧：对话区 */}
        <div className="training-conversation" style={{ flex: 1 }}>
          {/* 患者信息卡片 */}
          {caseData && (
            <div style={{ margin: "12px 16px", padding: 12, background: "#f8fafc", borderRadius: 8, border: "1px solid #e2e8f0", fontSize: "0.8rem" }}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>患者初始信息</div>
              <div>{caseData.patient_profile?.appearance || ""}</div>
              <div style={{ color: "#6b7280" }}>主诉：{caseData.initial_exposure?.chief_complaint || ""}</div>
              {!isExam && (caseData.training_focus || []).length > 0 && (
                <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {(caseData.training_focus || []).slice(0, 4).map((f, i) => (
                    <span key={i} style={{ fontSize: "0.65rem", background: "#fef3c7", color: "#92400e", padding: "2px 6px", borderRadius: 8 }}><Target size={10} style={{marginRight:2}} />{f}</span>
                  ))}
                </div>
              )}
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`msg-row ${msg.role === "student" ? "student" : "patient"}`}>
              <div className="msg-bubble"><p>{msg.content}</p></div>
            </div>
          ))}
          {followUpStateUpdates.map((state, i) => (
            <div key={`follow-up-state-${i}`} style={{ margin: "10px 16px", display: "flex", justifyContent: "center" }}>
              <div style={{
                width: "100%",
                maxWidth: 560,
                padding: 12,
                borderRadius: 8,
                border: `1px solid ${state.deteriorated ? "#fecaca" : "#bfdbfe"}`,
                background: state.deteriorated ? "#fef2f2" : "#eff6ff",
                color: "#111827",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                  <strong>{state.title || "候诊观察后患者状态"}</strong>
                  <span style={{ fontSize: "0.72rem", color: state.deteriorated ? "#b91c1c" : "#1d4ed8", fontWeight: 700 }}>
                    候诊观察记录
                  </span>
                </div>
                {state.state_name && <div style={{ fontSize: "0.78rem", marginBottom: 4 }}>状态：{state.state_name}</div>}
                {state.appearance && <div style={{ fontSize: "0.78rem", marginBottom: 4 }}>外观：{state.appearance}</div>}
                {state.expression && <div style={{ fontSize: "0.78rem" }}>当前表现：{state.expression}</div>}
              </div>
            </div>
          ))}
          {sending && <div className="msg-row patient"><div className="msg-bubble"><div className="typing-dots"><span /><span /><span /></div></div></div>}
          {timeLeft === 0 && <div className="time-up-banner">时间到，请提交分诊决策。</div>}
          <div ref={messagesEndRef} />
        </div>

        {/* 右侧：决策面板 */}
        <div style={{ width: 300, borderLeft: "1px solid #e5e7eb", padding: 16, overflowY: "auto", background: "#fafafa" }}>
          <h4 style={{ fontSize: "0.85rem", fontWeight: 700, marginBottom: 12 }}>分诊决策面板</h4>

{/* V2: 采集进度 + 变体提示 */}
          
            <div style={{ marginBottom: 12, padding: "6px 10px", background: "#fef3c7", borderRadius: 6, fontSize: "0.7rem", color: "#92400e" }}>
              
            </div>
          <div style={{ marginBottom: 16, padding: 10, background: "#fff", borderRadius: 6, border: "1px solid #e5e7eb" }}>
            <div style={{ fontSize: "0.72rem", color: "#6b7280", marginBottom: 4 }}>{!isExam ? "采集进度 (已覆盖/总需采集)" : "训练进行中"}</div>
            <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>
              {disclosedSlots.length > 0 ? `${disclosedSlots.length} / ${totalQuestions || disclosedSlots.length + 4}` : `${askedCount} / ${totalQuestions}`} 项
            </div>
            {disclosedSlots.length > 0 && (
              <div style={{ marginTop: 4, height: 4, borderRadius: 2, background: "#e5e7eb", overflow: "hidden" }}>
                <div style={{ height: "100%", borderRadius: 2, background: "#22c55e", width: `${Math.min(100, (disclosedSlots.length / (totalQuestions || disclosedSlots.length + 4)) * 100)}%`, transition: "width 0.3s ease" }} />
              </div>
            )}
          </div>

          {/* 第一眼观察 */}
          <div style={{ marginBottom: 16 }}>
            {observed.length === 0 ? (
              <div>
                <div style={{ fontSize: "0.72rem", fontWeight: 600, marginBottom: 4 }}>
                  第一眼观察 {!isExam && <span style={{ fontSize: "0.6rem", color: "#9ca3af" }}>(选择项目)</span>}
                </div>
                {obsOptions.length > 0 && obsOptions.map((item) => (
                  <button key={item.id} type="button" onClick={() => toggleObs(item.id)}
                    style={{
                      padding: "4px 8px", margin: "2px", borderRadius: 4, cursor: "pointer",
                      fontSize: "0.68rem", fontWeight: 500,
                      border: selectedObs.includes(item.id) ? "2px solid #d97706" : "1px solid #d1d5db",
                      background: selectedObs.includes(item.id) ? "#fffbeb" : "#fff",
                      color: selectedObs.includes(item.id) ? "#92400e" : "#6b7280",
                    }}
                  >{item.label}</button>
                ))}
                <button onClick={handleObserve} disabled={obsOptions.length > 0 && selectedObs.length === 0} style={{
                  width: "100%", padding: "8px", borderRadius: 6, border: "1px dashed #d97706", background: "#fffbeb",
                  color: "#d97706", cursor: selectedObs.length === 0 && obsOptions.length > 0 ? "not-allowed" : "pointer",
                  fontSize: "0.75rem", fontWeight: 500, marginTop: 6, opacity: selectedObs.length === 0 && obsOptions.length > 0 ? 0.5 : 1,
                }}>
                  <Eye size={14} style={{ marginRight: 4 }} />记录观察
                </button>
              </div>
            ) : (
              <div style={{ padding: 8, background: "#fff", borderRadius: 6, border: "1px solid #e5e7eb", fontSize: "0.7rem" }}>
                <div style={{ fontWeight: 700, marginBottom: 4, color: "#d97706" }}>已观察</div>
                {observed.map((o, i) => <div key={i} style={{ color: o.is_abnormal ? "#dc2626" : "#374151" }}>· {o.label}: {o.value === "未描述" ? "未描述（病例数据未配置）" : o.value?.substring(0, 30)}</div>)}
              </div>
            )}
          </div>

          {/* 生命体征 */}
          <div style={{ marginBottom: 16 }}>
            {!vitals ? (
              <div>
                <div style={{ fontSize: "0.72rem", fontWeight: 600, marginBottom: 4 }}>测量生命体征 {!isExam && <span style={{fontSize:"0.6rem",color:"#9ca3af"}}>(选择测量项目)</span>}</div>
                {measOptions.length > 0 && measOptions.map(item => (
                  <button key={item.id} type="button" onClick={() => toggleMeasure(item.id)} style={{
                    padding:"4px 8px", margin:"2px", borderRadius:4, cursor:"pointer", fontSize:"0.68rem", fontWeight:500,
                    border: selectedMeasureIds.includes(item.id) ? "2px solid #2563eb" : "1px solid #d1d5db",
                    background: selectedMeasureIds.includes(item.id) ? "#eff6ff" : "#fff", color: selectedMeasureIds.includes(item.id) ? "#1d4ed8" : "#6b7280"
                  }}>{item.label}</button>
                ))}
                {!isExam && <button onClick={() => handleMeasure(measOptions.map(m => m.id))} style={{
                  width:"100%", padding:"6px", borderRadius:4, border:"1px dashed #2563eb", background:"#eff6ff", color:"#2563eb", cursor:"pointer", fontSize:"0.7rem", marginTop:6
                }}>测量全部基础体征</button>}
                <button disabled={measOptions.length > 0 && selectedMeasureIds.length === 0} onClick={() => handleMeasure()} style={{
                  width:"100%", padding:"6px", borderRadius:4, border:"1px solid #2563eb", background:"#2563eb", color:"#fff", cursor: selectedMeasureIds.length === 0 && measOptions.length > 0 ? "not-allowed" : "pointer", fontSize:"0.7rem", marginTop:4, opacity: selectedMeasureIds.length === 0 && measOptions.length > 0 ? 0.5 : 1
                }}><Activity size={14} style={{marginRight:4}} />测量所选项目</button>
              </div>
            ) : (
              <div style={{ padding: 10, background: "#fff", borderRadius: 6, border: "1px solid #e5e7eb" }}>
                <div style={{ fontSize: "0.72rem", fontWeight: 700, marginBottom: 6 }}>生命体征</div>
                {vitals.map((v) => {
                  const valueText = v.display_value || `${v.value ?? ""}${v.unit ? ` ${v.unit}` : ""}`;
                  return (
                    <div key={v.id} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", padding: "2px 0", color: v.is_abnormal ? "#dc2626" : "#374151" }}>
                      <span>{v.label}</span>
                      <span style={{ fontWeight: 600 }}>{valueText} {v.is_abnormal && <AlertTriangle size={10} />}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 分诊等级 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: "0.72rem", fontWeight: 600, marginBottom: 6 }}>分诊等级</div>
            {LEVELS.map((l) => (
              <div key={l.value} onClick={() => setSelectedLevel(l.value)} style={{
                padding: "8px 10px", marginBottom: 4, borderRadius: 6, cursor: "pointer", fontSize: "0.75rem",
                border: `1px solid ${selectedLevel === l.value ? l.color : "#e5e7eb"}`,
                background: selectedLevel === l.value ? l.color + "15" : "#fff",
              }}>
                <span style={{ fontWeight: 600, color: l.color }}>{l.label}</span>
                <span style={{ marginLeft: 8, color: "#6b7280" }}>{l.desc}</span>
              </div>
            ))}
          </div>

          {/* 就诊区域 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: "0.72rem", fontWeight: 600, marginBottom: 6 }}>就诊区域</div>
            {ZONES.map((z) => (
              <div key={z.value} onClick={() => setSelectedZone(z.value)} style={{
                padding: "8px 10px", marginBottom: 4, borderRadius: 6, cursor: "pointer", fontSize: "0.75rem",
                border: `1px solid ${selectedZone === z.value ? z.color : "#e5e7eb"}`,
                background: selectedZone === z.value ? z.color + "15" : "#fff",
              }}>
                <span style={{ fontWeight: 600, color: z.color }}>{z.label}</span>
                <span style={{ marginLeft: 8, color: "#6b7280" }}>{z.desc}</span>
              </div>
            ))}
          </div>

          {/* 初步处置 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: "0.72rem", fontWeight: 600, marginBottom: 6 }}>初步处置</div>
            {DISPOSITIONS.map((d) => (
              <label key={d} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 0", fontSize: "0.75rem", cursor: "pointer" }}>
                <input type="checkbox" checked={selectedDispositions.includes(d)}
                  onChange={(e) => {
                    if (e.target.checked) setSelectedDispositions([...selectedDispositions, d]);
                    else setSelectedDispositions(selectedDispositions.filter((x) => x !== d));
                  }} />
                {d}
              </label>
            ))}
          </div>

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: "0.72rem", fontWeight: 600, marginBottom: 6 }}>分诊理由 / 高危信号记录</div>
            <textarea
              value={triageReason}
              onChange={(e) => setTriageReason(e.target.value)}
              disabled={submitted}
              rows={3}
              placeholder="记录支持分诊判断的关键依据，例如症状、生命体征、红旗信号或低估风险。"
              style={{ width: "100%", padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: "0.74rem", resize: "vertical", boxSizing: "border-box" }}
            />
          </div>

          <div style={{ marginBottom: 16, padding: 10, background: initialDecisionRecorded ? "#f0fdf4" : "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8 }}>
            <div style={{ fontSize: "0.72rem", fontWeight: 700, marginBottom: 6 }}>初始分诊决策</div>
            <button
              type="button"
              data-testid="record-initial-triage"
              disabled={!selectedLevel || !selectedZone || initialDecisionRecorded || submitted}
              onClick={handleInitialDecision}
              style={{
                width: "100%",
                padding: 8,
                borderRadius: 6,
                border: "1px solid #d97706",
                background: initialDecisionRecorded ? "#dcfce7" : "#fffbeb",
                color: initialDecisionRecorded ? "#15803d" : "#92400e",
                cursor: !selectedLevel || !selectedZone || initialDecisionRecorded || submitted ? "not-allowed" : "pointer",
                fontSize: "0.72rem",
                fontWeight: 700,
              }}
            >
              {initialDecisionRecorded ? `已记录：${selectedLevel} / ${selectedZone}` : "记录初始分诊"}
            </button>
          </div>

          <TriageFollowUpDecisionPanel
            visible={initialDecisionRecorded && !submitted}
            disabled={submitted}
            selectedOption={followUpOption}
            onSelect={(value) => {
              setFollowUpOption(value);
              setFollowUpDecisionRecorded(false);
            }}
            onSubmit={handleFollowUpDecision}
            decisionResult={followUpDecisionResult}
            examMode={isExam}
          />

          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: "0.72rem", fontWeight: 600, marginBottom: 6 }}>处置 / 候诊 / 交接说明</div>
            <textarea
              value={handoffNote}
              onChange={(e) => setHandoffNote(e.target.value)}
              disabled={submitted}
              rows={3}
              placeholder="记录通知医生、区域调整、等待告知、复评时间或异常报告要求。"
              style={{ width: "100%", padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: "0.74rem", resize: "vertical", boxSizing: "border-box" }}
            />
          </div>
        </div>
      </div>

      {/* 底部输入 */}
      <div className="training-input-bar">
        <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder={submitted ? "训练已提交" : "输入你的问题..."}
          disabled={sending || submitted} />
        <button className="send-btn" onClick={handleSend} disabled={!input.trim() || sending || submitted}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
