import { Clock, AlertTriangle, CheckCircle, Activity, ChevronRight } from "lucide-react";

const displayText = (value, fallback = "") => {
  if (value == null) return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => displayText(item)).filter(Boolean).join("、") || fallback;
  if (typeof value === "object") {
    return displayText(value.label ?? value.name ?? value.title ?? value.text ?? value.description ?? value.event_description, fallback);
  }
  return fallback;
};

export default function TriageTimelinePanel({ timeline, onAdvance, onReassess, loading, showReassessHint, canAdvance = true, canReassess = true }) {
  const events = timeline?.timeline_events || [];
  const pending = events.filter((e) => !e.triggered);
  const currentMinute = timeline?.current_minute || 0;
  const maxMinute = Math.max(currentMinute, ...events.map(e => e.scheduled_minute || 0), 30);

  // 计算所有时间标记点
  const markers = [];
  const seenMinutes = new Set();
  seenMinutes.add(0);
  markers.push({ minute: 0, label: "T0", isCurrent: currentMinute === 0, triggered: true });
  for (const ev of events) {
    const m = ev.scheduled_minute || 0;
    if (!seenMinutes.has(m) && m > 0) {
      seenMinutes.add(m);
      markers.push({ minute: m, label: `T${m}`, isCurrent: currentMinute >= m, triggered: ev.triggered || currentMinute >= m });
    }
  }
  markers.sort((a, b) => a.minute - b.minute);

  return (
    <div style={{ padding: 10, background: "#fff", borderRadius: 6, border: "1px solid #e5e7eb", marginBottom: 12 }}>
      <div style={{ fontSize: "0.78rem", fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
        <Clock size={14} /> 病例时间轴 (模拟第{currentMinute}分钟)
      </div>

      {/* 水平时间轴 */}
      <div style={{ position: "relative", height: 40, marginBottom: 8 }}>
        <div style={{
          position: "absolute", top: 18, left: 0, right: 0, height: 3,
          background: `linear-gradient(to right, #22c55e 0%, #22c55e ${(currentMinute / max(maxMinute, 1)) * 100}%, #e5e7eb ${(currentMinute / max(maxMinute, 1)) * 100}%)`,
          borderRadius: 2,
        }} />
        {markers.map((m, i) => {
          const leftPct = maxMinute > 0 ? (m.minute / maxMinute) * 100 : 0;
          return (
            <div key={i} style={{
              position: "absolute", top: 10, left: `${Math.min(leftPct, 95)}%`,
              transform: "translateX(-50%)", textAlign: "center",
            }}>
              <div style={{
                width: 16, height: 16, borderRadius: 9999,
                background: m.triggered ? (m.isCurrent ? "#2563eb" : "#22c55e") : "#d1d5db",
                border: `2px solid ${m.isCurrent ? "#1d4ed8" : "#fff"}`,
                margin: "0 auto",
              }} />
              <div style={{ fontSize: "0.55rem", fontWeight: 600, color: m.isCurrent ? "#2563eb" : "#6b7280", marginTop: 2 }}>
                {m.label}
              </div>
            </div>
          );
        })}
      </div>

      {/* 时间轴事件列表 */}
      <div style={{ marginBottom: 10 }}>
        {events.map((ev, i) => {
          const isCurrentEvent = ev.triggered && Math.abs(ev.scheduled_minute - currentMinute) <= 5;
          const eventText = displayText(ev.event_description || ev.patient_expression, "...");
          return (
            <div key={i} style={{
              padding: "5px 0", borderLeft: `2px solid ${ev.triggered ? "#22c55e" : "#d1d5db"}`,
              paddingLeft: 8, marginBottom: 2, fontSize: "0.7rem",
              color: ev.triggered ? "#374151" : "#9ca3af",
              background: isCurrentEvent ? "#f0fdf4" : "transparent",
            }}>
              <div style={{ fontWeight: 600 }}>
                {ev.triggered ? <CheckCircle size={10} style={{ color: "#22c55e", marginRight: 4 }} /> : <Clock size={10} style={{ marginRight: 4 }} />}
                {ev.scheduled_minute}分钟: {eventText.substring(0, 40)}
              </div>
              {ev.triggered && ev.requires_reassessment && (
                <div style={{ color: "#dc2626", fontSize: "0.65rem", marginTop: 2 }}>
                  <AlertTriangle size={10} /> 需要复评
                </div>
              )}
              {ev.triggered && ev.severe_error_if_ignored && (
                <div style={{ color: "#991b1b", fontSize: "0.6rem", marginTop: 1 }}>
                  ⛔ 忽略将触发严重错误
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 患者状态变化提示（practice 模式） */}
      {timeline?.patient_state?.state_name && (
        <div style={{ padding: "4px 8px", background: "#fef3c7", borderRadius: 4, fontSize: "0.65rem", marginBottom: 6, color: "#92400e" }}>
          当前: {displayText(timeline.patient_state.state_name)} — {displayText(timeline.patient_state.appearance).substring(0, 50)}
        </div>
      )}

      {/* 操作按钮 */}
      <div style={{ display: "flex", gap: 6 }}>
        {pending.length > 0 && (
          <button data-testid="advance-timeline" onClick={() => {
            const nextMinute = pending[0].scheduled_minute;
            const advanceBy = nextMinute - currentMinute;
            onAdvance(advanceBy > 0 ? advanceBy : pending[0].scheduled_minute);
          }}
            disabled={loading || !canAdvance} title={!canAdvance ? "请先完成初始分诊" : "推进到下一时间点"} style={{
              flex: 1, padding: "6px 10px", borderRadius: 6, border: "1px solid #2563eb",
              background: "#eff6ff", color: "#2563eb", cursor: loading || !canAdvance ? "not-allowed" : "pointer", fontSize: "0.72rem", fontWeight: 500,
              opacity: loading || !canAdvance ? 0.55 : 1,
            }}>
            <ChevronRight size={12} /> 推进时间
          </button>
        )}
        {showReassessHint && (
          <button data-testid="timeline-reassessment" onClick={onReassess} disabled={loading || !canReassess} title={!canReassess ? "初始分诊后才能复评" : "执行候诊复评"} style={{
            flex: 1, padding: "6px 10px", borderRadius: 6, border: "1px solid #d97706",
            background: "#fffbeb", color: "#d97706", cursor: loading || !canReassess ? "not-allowed" : "pointer", fontSize: "0.72rem", fontWeight: 500,
            opacity: loading || !canReassess ? 0.55 : 1,
          }}>
            <Activity size={12} /> 进行复评
          </button>
        )}
      </div>
    </div>
  );
}

function max(a, b) { return a > b ? a : b; }
