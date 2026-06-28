import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

const STATUS_LABELS = {
  complete: "完成",
  good: "较好",
  partial: "部分完成",
  missed: "未完成",
};

const STATUS_COLORS = {
  complete: "#16a34a",
  good: "#16a34a",
  partial: "#d97706",
  missed: "#dc2626",
};

const toArray = (value) => {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (value) return [value];
  return [];
};

const formatScore = (value) => {
  const n = Number(value || 0);
  return Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, "");
};

function CriterionList({ title, items, color, showStandardBasis, showImprovement = true }) {
  if (!items.length) return null;
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: "0.72rem", fontWeight: 700, color, marginBottom: 5 }}>{title}</div>
      {items.map((item, idx) => (
        <div key={`${item.id || item.label}-${idx}`} style={{
          padding: "8px 10px",
          border: "1px solid #e5e7eb",
          borderRadius: 8,
          background: "#fff",
          marginBottom: 6,
          fontSize: "0.74rem",
          lineHeight: 1.55,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
            <span style={{ fontWeight: 700, color: "#111827" }}>{item.label || item.criterion || "评分细则"}</span>
            <span style={{ fontWeight: 800, color: STATUS_COLORS[item.status] || color, whiteSpace: "nowrap" }}>
              {formatScore(item.score)}/{formatScore(item.max ?? item.max_score)}
            </span>
          </div>
          {item.deduction_reason && <div style={{ color: "#b91c1c" }}>扣分原因：{item.deduction_reason}</div>}
          {item.evidence && <div style={{ color: "#374151" }}>操作证据：{item.evidence}</div>}
          {showStandardBasis && item.standard_basis && <div style={{ color: "#1d4ed8" }}>标准依据：{item.standard_basis}</div>}
          {item.international_reference && <div style={{ color: "#6b7280" }}>参考框架：{item.international_reference}</div>}
          {showImprovement && item.improvement && <div style={{ color: "#047857" }}>改进建议：{item.improvement}</div>}
        </div>
      ))}
    </div>
  );
}

export default function ScoreBreakdownDetails({ detailScores, showStandardBasis = true }) {
  const entries = useMemo(() => Object.entries(detailScores || {}), [detailScores]);
  const firstWeakKey = useMemo(() => {
    const found = entries.find(([, dim]) => Number(dim?.score || 0) < Number(dim?.max || 1) * 0.7);
    return found?.[0] || "";
  }, [entries]);
  const [expanded, setExpanded] = useState(() => firstWeakKey ? { [firstWeakKey]: true } : {});

  if (!entries.length) return null;

  return (
    <div>
      <div style={{ fontSize: "0.76rem", color: "#6b7280", marginBottom: 10 }}>
        点击任一分项可查看扣分点、操作证据、标准依据和改进建议。总分仍由病例标准答案与规则引擎决定。
      </div>
      {entries.map(([name, dim]) => {
        const score = Number(dim?.score || 0);
        const max = Math.max(Number(dim?.max || 1), 1);
        const status = dim?.status || (score >= max * 0.7 ? "good" : score > 0 ? "partial" : "missed");
        const color = STATUS_COLORS[status] || (score >= max * 0.7 ? "#16a34a" : score > 0 ? "#d97706" : "#dc2626");
        const criteria = toArray(dim?.criteria);
        const missedCriteria = criteria.filter((item) => item?.deduction_reason || item?.missed_reason || item?.status === "missed");
        const metCriteria = criteria.filter((item) => !missedCriteria.includes(item));
        const isOpen = Boolean(expanded[name]);
        return (
          <div key={name} style={{ marginBottom: 10, border: "1px solid #e5e7eb", borderRadius: 8, overflow: "hidden", background: "#fff" }}>
            <button
              type="button"
              onClick={() => setExpanded((prev) => ({ ...prev, [name]: !prev[name] }))}
              style={{
                width: "100%",
                border: "none",
                background: "#fff",
                padding: "10px 12px",
                cursor: "pointer",
                textAlign: "left",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  <span style={{ fontSize: "0.82rem", fontWeight: 700, color: "#111827" }}>{name}</span>
                  <span style={{ padding: "2px 7px", borderRadius: 999, background: `${color}18`, color, fontSize: "0.68rem", fontWeight: 700 }}>
                    {STATUS_LABELS[status] || status}
                  </span>
                </div>
                <span style={{ fontSize: "0.82rem", fontWeight: 800, color, whiteSpace: "nowrap" }}>
                  {formatScore(score)} / {formatScore(max)}
                </span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: "#e5e7eb", overflow: "hidden" }}>
                <div style={{ height: "100%", borderRadius: 3, background: color, width: `${Math.max(0, Math.min(100, (score / max) * 100))}%` }} />
              </div>
              {dim?.summary && <div style={{ marginTop: 6, fontSize: "0.7rem", color: "#6b7280" }}>{dim.summary}</div>}
            </button>
            {isOpen && (
              <div style={{ padding: "0 12px 12px", background: "#f8fafc", borderTop: "1px solid #f3f4f6" }}>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", paddingTop: 10, fontSize: "0.7rem" }}>
                  <span style={{ padding: "3px 8px", borderRadius: 999, background: "#fff7ed", color: "#c2410c", fontWeight: 700 }}>
                    扣分 {formatScore(dim?.lost_score ?? (max - score))}
                  </span>
                  {missedCriteria.length > 0 && (
                    <span style={{ padding: "3px 8px", borderRadius: 999, background: "#fef2f2", color: "#b91c1c", fontWeight: 700 }}>
                      {missedCriteria.length} 个需改进点
                    </span>
                  )}
                  {metCriteria.length > 0 && (
                    <span style={{ padding: "3px 8px", borderRadius: 999, background: "#f0fdf4", color: "#15803d", fontWeight: 700 }}>
                      {metCriteria.length} 个已完成点
                    </span>
                  )}
                </div>

                <CriterionList title="扣分点" items={missedCriteria} color="#b91c1c" showStandardBasis={showStandardBasis} />
                <CriterionList title="已完成证据" items={metCriteria} color="#15803d" showStandardBasis={showStandardBasis} showImprovement={false} />

                {(showStandardBasis && dim?.standard_basis) && (
                  <div style={{ marginTop: 8, padding: 8, borderRadius: 8, background: "#eff6ff", color: "#1e40af", fontSize: "0.73rem" }}>
                    <b>本项标准依据：</b>{dim.standard_basis}
                  </div>
                )}
                {dim?.international_reference && (
                  <div style={{ marginTop: 8, padding: 8, borderRadius: 8, background: "#f9fafb", color: "#4b5563", fontSize: "0.73rem" }}>
                    <b>国际分诊框架参考：</b>{dim.international_reference}
                  </div>
                )}
                {missedCriteria.length > 0 && dim?.improvement && (
                  <div style={{ marginTop: 8, padding: 8, borderRadius: 8, background: "#f0fdf4", color: "#047857", fontSize: "0.73rem" }}>
                    <b>下一步训练建议：</b>{dim.improvement}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
