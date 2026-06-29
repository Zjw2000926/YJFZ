const OPTIONS = [
  { id: "complete_no_reassessment", label: "完成分诊，无需复评" },
  { id: "observe_waiting", label: "安排候诊观察" },
  { id: "reassess_5", label: "5分钟后复评" },
  { id: "reassess_10", label: "10分钟后复评" },
  { id: "reassess_15", label: "15分钟后复评" },
  { id: "reassess_30", label: "30分钟后复评" },
  { id: "remeasure_vitals_now", label: "立即再次测量生命体征" },
  { id: "upgrade_notify_doctor", label: "立即升级处理/通知医生" },
  { id: "continue_history", label: "继续补充关键病史" },
  { id: "other", label: "其他处理措施" },
];

export default function TriageFollowUpDecisionPanel({
  visible,
  disabled,
  selectedOption,
  onSelect,
  onSubmit,
  decisionResult,
  examMode = false,
}) {
  if (!visible) return null;
  return (
    <div
      data-testid="follow-up-decision-panel"
      style={{
        marginTop: 10,
        padding: 10,
        background: "#f8fafc",
        border: "1px solid #cbd5e1",
        borderRadius: 8,
      }}
    >
      <div style={{ fontSize: "0.72rem", fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>
        候诊与复评决策
      </div>
      <div style={{ fontSize: "0.66rem", color: "#64748b", marginBottom: 8 }}>
        初始分诊后，请根据患者表现、生命体征和风险因素主动判断后续管理策略。
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
        {OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(option.id)}
            style={{
              padding: "6px 7px",
              borderRadius: 6,
              border: selectedOption === option.id ? "2px solid #2563eb" : "1px solid #d1d5db",
              background: selectedOption === option.id ? "#eff6ff" : "#fff",
              color: selectedOption === option.id ? "#1d4ed8" : "#334155",
              cursor: disabled ? "not-allowed" : "pointer",
              fontSize: "0.64rem",
              textAlign: "left",
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        data-testid="submit-follow-up-decision"
        disabled={disabled || !selectedOption}
        onClick={onSubmit}
        style={{
          width: "100%",
          marginTop: 8,
          padding: 7,
          borderRadius: 6,
          border: "1px solid #2563eb",
          background: selectedOption ? "#2563eb" : "#bfdbfe",
          color: "#fff",
          cursor: disabled || !selectedOption ? "not-allowed" : "pointer",
          fontSize: "0.68rem",
          fontWeight: 700,
        }}
      >
        记录后续管理决策
      </button>
      {decisionResult?.feedback_message && !examMode && (
        <div
          style={{
            marginTop: 8,
            padding: 7,
            background: decisionResult.whether_correct ? "#f0fdf4" : "#fff7ed",
            color: decisionResult.whether_correct ? "#166534" : "#9a3412",
            borderRadius: 6,
            fontSize: "0.66rem",
          }}
        >
          {decisionResult.feedback_message}
        </div>
      )}
    </div>
  );
}
