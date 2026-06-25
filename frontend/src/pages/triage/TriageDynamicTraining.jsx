import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, User, Send, Clock, Activity, Phone, Eye } from "lucide-react";
import { startTriageTraining, sendTriageMessage, measureTriageVitals, submitTriage,
         getTriageTimeline, advanceTriageTimeline, reassessTriagePatient,
         getTriageCaseDetail, getTriageRecord, recordInitialDecision, notifyDoctor, saveTrainingNotes,
         getDynamicTimeline } from "../../api";
import { useToast } from "../../components/useToast";
import { useConfirm } from "../../components/ui/useConfirm";
import TriageTimelinePanel from "../../components/triage/TriageTimelinePanel";
import { calculateTimeLeftSeconds, formatCountdownTime, getPositiveInt, getTrainingTimerEndMs } from "../../utils/trainingTimer";

const LEVELS = [
  { value: "Ⅰ级", label: "Ⅰ级(濒危)", color: "#dc2626", testId: "1" },
  { value: "Ⅱ级", label: "Ⅱ级(危重)", color: "#ea580c", testId: "2" },
  { value: "Ⅲ级", label: "Ⅲ级(急症)", color: "#ca8a04", testId: "3" },
  { value: "Ⅳ级", label: "Ⅳ级(非急症)", color: "#16a34a", testId: "4" },
];

const STAGE_LABELS = new Set([
  "NOT_STARTED", "ARRIVAL", "FIRST_LOOK", "HISTORY_TAKING", "INITIAL_VITALS",
  "INITIAL_TRIAGE", "WAITING", "REASSESSMENT_DUE", "DETERIORATED",
  "REASSESSMENT", "RE_TRIAGE", "FINAL_DISPOSITION", "COMPLETED",
]);

const displayText = (value, fallback = "") => {
  if (value == null) return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => displayText(item)).filter(Boolean).join("、") || fallback;
  if (typeof value === "object") {
    return displayText(value.label ?? value.name ?? value.title ?? value.text ?? value.description ?? value.event_description, fallback);
  }
  return fallback;
};

const stageText = (value) => {
  const text = displayText(value);
  return STAGE_LABELS.has(text) ? text : "ARRIVAL";
};

export default function TriageDynamicTraining() {
  const { recordId: paramId } = useParams();
  const navigate = useNavigate();
  const { success, error, warning, info } = useToast();
  const { confirm } = useConfirm();
  const initialQuery = new URLSearchParams(window.location.search);
  const initialLimitSeconds = (getPositiveInt(initialQuery.get("time_limit")) || 8) * 60;
  const timerEndsAtRef = useRef(null);
  const startedRef = useRef(false);

  const [recordId, setRecordId] = useState(paramId);
  const [caseData, setCaseData] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [vitals, setVitals] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [selectedLevel, setSelectedLevel] = useState(null);
  const [selectedZone, setSelectedZone] = useState(null);
  // P2-3: 分离初始分诊和复评分诊
  const [initialLevel, setInitialLevel] = useState(null);
  const [initialZone, setInitialZone] = useState(null);
  const [reassessmentLevel] = useState(null);
  const [reassessmentZone] = useState(null);
  const [reassessmentInterval, setReassessmentInterval] = useState(30);
  const [doctorNotified, setDoctorNotified] = useState(false);
  const [selectedMeasureIds, setSelectedMeasureIds] = useState([]);
  const [observed, setObserved] = useState([]);
  const [selectedObs, setSelectedObs] = useState([]);
  const [noteInput, setNoteInput] = useState("");
  const [showNoteInput, setShowNoteInput] = useState(false);
  const [timeLeft, setTimeLeft] = useState(initialLimitSeconds);
  const [timerStarted, setTimerStarted] = useState(false);

  const measOptions = caseData?.measurement_options || [];
  const obsOptions = caseData?.observation_options || [];
  const messagesEndRef = useRef(null);
  const currentPatientState = timeline?.patient_state || {};
  const currentStage = stageText(timeline?.current_stage || currentPatientState.stage);
  const queryMode = new URLSearchParams(window.location.search).get("mode");
  const currentMode = queryMode || timeline?.mode || "practice";
  const isExamMode = ["exam", "osce"].includes(currentMode);
  const canEnterWaiting = Boolean(initialLevel);
  const canAdvanceTimeline = canEnterWaiting && !submitted && !loading;
  const canReassess = canEnterWaiting && !submitted && !loading;
  const selectedOrInitialZone = selectedZone || initialZone;
  const getDefaultMeasureIds = () => selectedMeasureIds.length > 0 ? selectedMeasureIds : measOptions.map((m) => m.id);
  const syncTimerFromRecord = useCallback((record, fallbackLimitMinutes) => {
    const limitMinutes = getPositiveInt(record?.time_limit_minutes) || getPositiveInt(fallbackLimitMinutes) || 8;
    timerEndsAtRef.current = getTrainingTimerEndMs(record, fallbackLimitMinutes);
    setTimeLeft(calculateTimeLeftSeconds(record?.started_at, limitMinutes));
  }, []);
  const refreshTimeline = async () => {
    if (!recordId) return null;
    const tl = await getDynamicTimeline(recordId);
    setTimeline(tl.data);
    return tl.data;
  };

  const toggleObs = (id) => { setSelectedObs(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]); };
  const toggleMeasure = (id) => { setSelectedMeasureIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]); };

  // init
  useEffect(() => {
    const cid = new URLSearchParams(window.location.search).get("case");
    const query = new URLSearchParams(window.location.search);
    const mode = query.get("mode") || "practice";
    const taskId = query.get("task_id");
    const timeLimit = query.get("time_limit") ? Number(query.get("time_limit")) : null;
    if (recordId) {
      // Restore existing training
      getTriageTimeline(recordId).then(({ data }) => setTimeline(data)).catch(() => {});
      getTriageRecord(recordId).then(({ data }) => {
        const record = data.record;
        if (!record || record.status !== "in_progress") {
          navigate(`/triage/record/${recordId}`, { replace: true });
          return;
        }
        setMessages(record.messages?.length ? record.messages.map((m) => ({ role: m.role, content: m.content })) : []);
        syncTimerFromRecord(record, timeLimit);
        setTimerStarted(true);
        const recordCaseId = record.case_external_id || cid;
        if (recordCaseId) getTriageCaseDetail(recordCaseId).then(({ data }) => setCaseData(data.case)).catch(() => {});
      }).catch(() => {});
      if (cid) getTriageCaseDetail(cid).then(({ data }) => setCaseData(data.case)).catch(() => {});
      return;
    }
    // Start new dynamic training from URL param
    if (startedRef.current) return;
    startedRef.current = true;
    if (!cid) { navigate("/triage"); return; }
    getTriageCaseDetail(cid).then(({ data }) => setCaseData(data.case)).catch(() => {});
    startTriageTraining(cid, "default", { mode, taskId, timeLimitMinutes: timeLimit }).then(({ data }) => {
      setRecordId(data.record_id);
      setMessages([{ role: "patient", content: data.opening_line }]);
      syncTimerFromRecord(data, timeLimit);
      setTimerStarted(true);
      const params = new URLSearchParams(window.location.search);
      params.set("case", cid);
      navigate(`/triage/dynamic/${data.record_id}?${params.toString()}`, { replace: true });
    }).catch(() => { error("启动失败"); navigate("/triage"); });
  }, [recordId, navigate, error, syncTimerFromRecord]);

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

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // Send message
  const handleSend = async () => {
    const content = input.trim();
    if (!content || loading) return;
    setInput("");
    setMessages((p) => [...p, { role: "student", content }]);
    setLoading(true);
    try {
      const { data } = await sendTriageMessage(recordId, content);
      setMessages((p) => [...p, { role: "patient", content: data.reply }]);
    } catch { error("发送失败"); }
    finally { setLoading(false); }
  };

  // Measure
  const handleMeasure = async (mids = []) => {
    try {
      const ids = mids.length > 0 ? mids : selectedMeasureIds;
      if (measOptions.length > 0 && ids.length === 0) { warning("请选择要测量的项目"); return []; }
      const { data } = await measureTriageVitals(recordId, ids);
      const results = data.measurements || [];
      setVitals(results);
      success("生命体征已测量");
      await refreshTimeline().catch(() => {});
      return results;
    } catch { error("测量失败"); return []; }
  };

  // Advance timeline
  const handleAdvance = async (mins) => {
    if (!initialLevel) { warning("请先记录初始分诊，再进入候诊时间轴"); return; }
    if (submitted || loading) return;
    try {
      const { data } = await advanceTriageTimeline(recordId, mins || 5);
      if (data.events?.length > 0) {
        for (const ev of data.events) {
          if (ev.patient_expression) {
            setMessages((p) => [...p, { role: "patient", content: ev.patient_expression }]);
          }
        }
        info(`时间推进到第${data.current_minute}分钟`);
      }
      await refreshTimeline();
    } catch { error("时间推进失败"); }
  };

  // Reassess
  const handleReassess = async () => {
    if (!initialLevel) { warning("请先完成初始分诊，再执行复评"); return; }
    const ok = await confirm({ title: "执行复评", message: "将重新测量生命体征并进行复评估", confirmLabel: "确认复评" });
    if (!ok) return;
    try {
      const latest = await handleMeasure(getDefaultMeasureIds());
            const nowIds = (latest || []).map(m => m.id);
            const payload = { measured_items: nowIds, symptom_change_questioned: true,
                         selected_level: selectedLevel, selected_zone: selectedZone || "黄区" };
      const { data } = await reassessTriagePatient(recordId, payload);
      if (data.upgrade_needed) {
        warning("根据规则引擎，需要升级分诊等级！");
      } else {
        success("复评完成");
      }
      await refreshTimeline();
    } catch { error("复评失败"); }
  };

  // P2-3: 初始分诊决策（使用分离的 initialLevel/initialZone/reassessmentInterval）
  const handleInitialDecision = async () => {
    if (!selectedLevel) { warning("请先选择分诊等级"); return; }
    try {
      const zone = selectedZone || "黄区";
      await recordInitialDecision(recordId, { level: selectedLevel, zone, reassessment_minutes: reassessmentInterval, reason: "" });
      setInitialLevel(selectedLevel);
      setInitialZone(zone);
      setSelectedZone(zone);
      success(`初始分诊已记录 (${selectedLevel}/${zone}，${reassessmentInterval}分钟复评) — 进入候诊`);
      await refreshTimeline();
    } catch { error("记录初始分诊失败"); }
  };

  // P2-3: 复评分诊（使用分离的 reassessmentLevel/reassessmentZone/doctorNotified）
  const handleReassessWithDecision = async () => {
    if (!initialLevel) { warning("请先完成初始分诊，再执行复评"); return; }
    const ok = await confirm({ title: "执行复评", message: "将重新测量生命体征并进行复评估", confirmLabel: "确认复评" });
    if (!ok) return;
    try {
      const latest = await handleMeasure(getDefaultMeasureIds());
      const nowIds = (latest || []).map(m => m.id);
      const payload = { measured_items: nowIds, symptom_change_questioned: true,
                       selected_level: reassessmentLevel || selectedLevel,
                       selected_zone: reassessmentZone || selectedZone || "黄区",
                       notify_doctor: doctorNotified };
      const { data } = await reassessTriagePatient(recordId, payload);
      if (data.upgrade_needed) {
        warning("根据规则引擎，需要升级分诊等级！");
      } else {
        success("复评完成");
      }
      if (doctorNotified) {
        await notifyDoctor(recordId, { reason: "复评后通知医生" });
      }
      await refreshTimeline();
    } catch { error("复评失败"); }
  };

  // 通知医生
  const handleNotifyDoctor = async () => {
    try {
      setDoctorNotified(true);
      await notifyDoctor(recordId, { reason: "患者病情恶化，需要医生评估" });
      success("已通知医生");
      await refreshTimeline();
    } catch { error("通知医生失败"); setDoctorNotified(false); }
  };

  // P2-3: 保存说明（textarea 替代 prompt）
  const handleSaveNotes = async () => {
    const note = noteInput.trim();
    if (!note) { warning("请输入记录说明"); return; }
    try {
      await saveTrainingNotes(recordId, { content: note });
      setNoteInput("");
      setShowNoteInput(false);
      success("说明已保存");
    } catch { error("保存失败"); }
  };

  // Submit
  const handleSubmit = async () => {
    if (submitted || loading) return;
    if (!selectedLevel) { warning("请选择分诊等级"); return; }
    if (!selectedOrInitialZone) { warning("请选择就诊区域"); return; }
    const ok = await confirm({ title: "提交分诊", message: "确定提交吗？", confirmLabel: "确定", danger: true });
    if (!ok) return;
    setLoading(true);
    try {
      const { data } = await submitTriage(recordId, { level: selectedLevel, zone: selectedOrInitialZone });
      setSubmitted(true);
      navigate(`/triage/record/${recordId}`, { state: { score: data.score, record: data.record } });
    } catch { error("提交失败"); }
    finally { setLoading(false); }
  };

  return (
    <div className="training-shell">
      <header className="training-topbar">
        <button className="training-back" onClick={() => navigate("/triage")}><ArrowLeft size={20} /></button>
        <div className="training-patient-identity">
          <div className="training-patient-avatar"><User size={20} /></div>
          <div>
            <div className="training-patient-name">{caseData?.display_name || "动态病例"}</div>
            <div className="training-patient-desc">{timeline ? `模拟第${timeline.current_minute}分钟` : "初诊"}</div>
          </div>
        </div>
        <div className="training-timer" style={timeLeft <= 120 ? { background: "#fef2f2", borderColor: "#fca5a5", color: "#dc2626" } : {}}>
          <Clock size={16} /><span>{formatCountdownTime(timeLeft)}</span>
        </div>
        {!submitted && (
          <button data-testid="submit-triage" className="training-end-btn" onClick={handleSubmit} disabled={!selectedLevel || !selectedOrInitialZone || loading}>
            <Phone size={16} /><span>{loading ? "提交中" : "提交分诊"}</span>
          </button>
        )}
      </header>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <div className="training-conversation" style={{ flex: 1 }}>
          {caseData && (
            <div style={{ margin: "12px 16px", padding: 12, background: "#f8fafc", borderRadius: 8, fontSize: "0.8rem" }}>
              <span style={{ fontWeight: 700 }}>动态病例</span>: {displayText(caseData.initial_exposure?.chief_complaint, "待评估")}
              <div style={{ marginTop: 6, color: "#6b7280" }}>
                本系统仅用于教学训练，不用于真实临床分诊或诊疗决策。
              </div>
            </div>
          )}
          {timeline && (
            <div style={{ margin: "0 16px 12px", padding: 12, background: currentPatientState.deteriorated ? "#fef2f2" : "#fff", border: `1px solid ${currentPatientState.deteriorated ? "#fecaca" : "#e5e7eb"}`, borderRadius: 8, fontSize: "0.78rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                <strong>当前患者状态</strong>
                <span style={{ color: "#6b7280" }}>阶段 {currentStage} · 模拟第{timeline.current_minute || 0}分钟</span>
              </div>
              <div>外观：{displayText(currentPatientState.appearance, "待观察")}</div>
              {displayText(currentPatientState.expression) && <div>患者表达：{displayText(currentPatientState.expression)}</div>}
              {!isExamMode && currentPatientState.reassessment_due && (
                <div style={{ color: "#b45309", marginTop: 4 }}>提示：当前状态需要考虑复评。</div>
              )}
            </div>
          )}
          {timeLeft === 0 && <div className="time-up-banner">时间到，请提交分诊决策。</div>}
          {messages.map((msg, i) => (
            <div key={i} className={`msg-row ${msg.role === "student" ? "student" : "patient"}`}>
              <div className="msg-bubble"><p>{displayText(msg.content, "已记录")}</p></div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div style={{ width: 280, borderLeft: "1px solid #e5e7eb", padding: 12, overflowY: "auto", background: "#fafafa" }}>
          <h4 style={{ fontSize: "0.8rem", fontWeight: 700, marginBottom: 8 }}>分诊决策 + 时间线</h4>

          {selectedZone && <span style={{fontSize:'0.7rem',color:'#6b7280'}}>{selectedZone}</span>}
          <div style={{fontSize:'0.7rem',fontWeight:600,marginBottom:4,marginTop:8}}>就诊区域</div>
          {[{id:'red',value:'红区',label:'红区',color:'#dc2626'},{id:'yellow',value:'黄区',label:'黄区',color:'#d97706'},{id:'green',value:'绿区',label:'绿区',color:'#16a34a'},{id:'fast',value:'专病绿色通道',label:'专病绿色通道',color:'#2563eb'},{id:'isolation',value:'隔离区域',label:'隔离区域',color:'#9333ea'}].map(z=>(
            <div key={z.value} data-testid={`zone-option-${z.id}`} onClick={()=>setSelectedZone(z.value)} style={{padding:'5px 8px',marginBottom:2,borderRadius:4,cursor:'pointer',fontSize:'0.7rem',border:'1px solid '+(selectedZone===z.value?z.color:'#e5e7eb'),background:selectedZone===z.value?z.color+'15':'#fff'}}>
              <span style={{fontWeight:600,color:z.color}}>{z.label}</span>
            </div>
          ))}
          {timeline && <TriageTimelinePanel timeline={timeline} onAdvance={handleAdvance}
            onReassess={handleReassess} loading={loading}
            canAdvance={canAdvanceTimeline}
            canReassess={canReassess}
            showReassessHint={!isExamMode && timeline.timeline_events?.some((e) => e.triggered && e.requires_reassessment)} />}

          {/* 第一眼观察 */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: "0.7rem", fontWeight: 600, marginBottom: 4 }}>第一眼观察</div>
            {obsOptions.length > 0 && obsOptions.map((item) => (
              <button key={item.id} type="button" onClick={() => toggleObs(item.id)}
                style={{
                  padding: "3px 6px", margin: "1px", borderRadius: 4, cursor: "pointer",
                  fontSize: "0.65rem", fontWeight: 500,
                  border: selectedObs.includes(item.id) ? "2px solid #d97706" : "1px solid #d1d5db",
                  background: selectedObs.includes(item.id) ? "#fffbeb" : "#fff",
                  color: selectedObs.includes(item.id) ? "#92400e" : "#6b7280",
                }}
              >{displayText(item.label, item.id)}</button>
            ))}
            <button onClick={() => { if (selectedObs.length > 0) { setObserved(prev => [...prev, ...selectedObs.map(id => ({ id, label: obsOptions.find(o => o.id === id)?.label || id, value: "已记录" }))]); setSelectedObs([]); success("观察已记录"); } }} disabled={selectedObs.length === 0}
              style={{ width: "100%", padding: 4, borderRadius: 4, border: "1px dashed #d97706", background: "#fffbeb",
                color: "#d97706", cursor: selectedObs.length === 0 ? "not-allowed" : "pointer", fontSize: "0.65rem", marginTop: 2, opacity: selectedObs.length === 0 ? 0.5 : 1 }}>
              <Eye size={12} style={{ marginRight: 2 }} />记录观察
            </button>
            {observed.length > 0 && (
              <div style={{ marginTop: 4, fontSize: "0.62rem", color: "#6b7280" }}>
                {observed.map((o, i) => <div key={i}>· {displayText(o.label, o.id)}: {displayText(o.value).substring(0, 20)}</div>)}
              </div>
            )}
          </div>

          {/* 生命体征 */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: "0.7rem", fontWeight: 600, marginBottom: 4 }}>测量生命体征</div>
            {measOptions.length > 0 && measOptions.map((item) => (
              <button key={item.id} type="button" onClick={() => toggleMeasure(item.id)}
                style={{
                  padding: "3px 6px", margin: "1px", borderRadius: 4, cursor: "pointer",
                  fontSize: "0.65rem", fontWeight: 500,
                  border: selectedMeasureIds.includes(item.id) ? "2px solid #2563eb" : "1px solid #d1d5db",
                  background: selectedMeasureIds.includes(item.id) ? "#eff6ff" : "#fff",
                  color: selectedMeasureIds.includes(item.id) ? "#1d4ed8" : "#6b7280",
                }}
              >{displayText(item.label, item.id)}</button>
            ))}
            <button data-testid="measure-all-vitals" onClick={() => handleMeasure(measOptions.map(m => m.id))}
              style={{ width: "100%", padding: 4, borderRadius: 4, border: "1px dashed #2563eb", background: "#eff6ff", color: "#2563eb", cursor: "pointer", fontSize: "0.65rem", marginTop: 2 }}>
              测量全部基础体征
            </button>
            <button onClick={() => handleMeasure()} disabled={measOptions.length > 0 && selectedMeasureIds.length === 0}
              style={{ width: "100%", padding: 4, borderRadius: 4, border: "1px solid #2563eb", background: "#2563eb", color: "#fff",
                cursor: selectedMeasureIds.length === 0 && measOptions.length > 0 ? "not-allowed" : "pointer", fontSize: "0.65rem", marginTop: 2,
                opacity: selectedMeasureIds.length === 0 && measOptions.length > 0 ? 0.5 : 1 }}>
              <Activity size={12} style={{ marginRight: 2 }} />测量所选项目
            </button>
          </div>

          {vitals && (
            <div style={{ marginBottom: 10, padding: 8, background: "#fff", borderRadius: 6, border: "1px solid #e5e7eb", fontSize: "0.7rem" }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>生命体征结果</div>
              {vitals.map((v) => {
                const valueText = v.display_value || `${v.value ?? ""}${v.unit ? ` ${v.unit}` : ""}`;
                return (
                  <div key={v.id} style={{ display: "flex", justifyContent: "space-between", padding: "1px 0", color: v.is_abnormal ? "#dc2626" : "#374151" }}>
                    <span>{displayText(v.label, v.id)}</span><span style={{ fontWeight: 600 }}>{displayText(valueText, "-")}</span>
                  </div>
                );
              })}
            </div>
          )}

          <div style={{ fontSize: "0.7rem", fontWeight: 600, marginBottom: 4 }}>分诊等级</div>
          {LEVELS.map((l) => (
            <div key={l.value} data-testid={`triage-level-${l.testId}`} onClick={() => setSelectedLevel(l.value)} style={{
              padding: "5px 8px", marginBottom: 2, borderRadius: 4, cursor: "pointer", fontSize: "0.7rem",
              border: `1px solid ${selectedLevel === l.value ? l.color : "#e5e7eb"}`,
              background: selectedLevel === l.value ? l.color + "15" : "#fff",
            }}><span style={{ fontWeight: 600, color: l.color }}>{l.label}</span></div>
          ))}

          {/* P2-3: 动态操作 — 初始分诊区 */}
          <div style={{ marginTop: 8, padding: "6px 8px", background: "#fffbeb", borderRadius: 4, border: "1px solid #fde68a" }}>
            <div style={{ fontSize: "0.65rem", fontWeight: 600, marginBottom: 4, color: "#92400e" }}>初始分诊决策</div>
            <div style={{ display: "flex", gap: 4, marginBottom: 4 }}>
              <select value={reassessmentInterval} onChange={e => setReassessmentInterval(Number(e.target.value))}
                style={{ flex: 1, padding: "2px 4px", fontSize: "0.6rem", borderRadius: 3, border: "1px solid #d1d5db" }}>
                <option value={10}>10分钟复评</option>
                <option value={15}>15分钟复评</option>
                <option value={30}>30分钟复评</option>
                <option value={60}>60分钟复评</option>
              </select>
            </div>
            <button data-testid="record-initial-triage" onClick={handleInitialDecision} disabled={!selectedLevel || submitted || initialLevel}
              style={{ width: "100%", padding: 4, borderRadius: 3, border: "1px solid #d97706", background: initialLevel ? "#f0fdf4" : "#fffbeb", color: initialLevel ? "#16a34a" : "#92400e", cursor: selectedLevel && !submitted && !initialLevel ? "pointer" : "default", fontSize: "0.62rem", opacity: selectedLevel && !submitted && !initialLevel ? 1 : 0.7 }}>
              {initialLevel ? `已记录: ${initialLevel}/${initialZone||"黄区"}` : "记录初始分诊"}
            </button>
          </div>

          {/* P2-3: 复评/升级区 */}
          <div style={{ marginTop: 6, padding: "6px 8px", background: "#fef2f2", borderRadius: 4, border: "1px solid #fecaca" }}>
            <div style={{ fontSize: "0.65rem", fontWeight: 600, marginBottom: 4, color: "#991b1b" }}>复评与升级</div>
            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: "0.6rem", marginBottom: 4, cursor: "pointer" }}>
              <input type="checkbox" checked={doctorNotified} onChange={e => setDoctorNotified(e.target.checked)} />
              通知医生
            </label>
            <div style={{ display: "flex", gap: 3 }}>
              <button data-testid="perform-reassessment" onClick={handleReassessWithDecision} disabled={submitted}
                style={{ flex: 1, padding: 4, borderRadius: 3, border: "1px solid #d97706", background: "#fffbeb", color: "#d97706", cursor: submitted ? "not-allowed" : "pointer", fontSize: "0.62rem" }}>
                执行复评
              </button>
              <button data-testid="notify-doctor" onClick={handleNotifyDoctor} disabled={submitted}
                style={{ flex: 1, padding: 4, borderRadius: 3, border: "1px solid #dc2626", background: doctorNotified ? "#f0fdf4" : "#fef2f2", color: doctorNotified ? "#16a34a" : "#dc2626", cursor: submitted ? "not-allowed" : "pointer", fontSize: "0.62rem" }}>
                {doctorNotified ? "已通知" : "通知医生"}
              </button>
            </div>
          </div>

          {/* P2-3: 记录说明 textarea */}
          <div style={{ marginTop: 6 }}>
            {!showNoteInput ? (
              <button onClick={() => setShowNoteInput(true)} disabled={submitted}
                style={{ width: "100%", padding: 4, borderRadius: 3, border: "1px solid #6b7280", background: "#f9fafb", color: "#374151", cursor: submitted ? "not-allowed" : "pointer", fontSize: "0.62rem" }}>
                记录说明
              </button>
            ) : (
              <div>
                <textarea value={noteInput} onChange={e => setNoteInput(e.target.value)}
                  placeholder="输入记录说明..." rows={2}
                  style={{ width: "100%", padding: 4, fontSize: "0.62rem", borderRadius: 3, border: "1px solid #d1d5db", resize: "vertical" }} />
                <div style={{ display: "flex", gap: 3, marginTop: 2 }}>
                  <button onClick={handleSaveNotes} style={{ flex: 1, padding: 3, borderRadius: 3, border: "1px solid #2563eb", background: "#eff6ff", color: "#2563eb", cursor: "pointer", fontSize: "0.6rem" }}>保存</button>
                  <button onClick={() => { setShowNoteInput(false); setNoteInput(""); }} style={{ padding: "3px 8px", borderRadius: 3, border: "1px solid #d1d5db", background: "#fff", cursor: "pointer", fontSize: "0.6rem" }}>取消</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="training-input-bar">
        <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="输入你的问题..." disabled={loading || submitted} />
        <button className="send-btn" onClick={handleSend} disabled={!input.trim() || loading || submitted}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
