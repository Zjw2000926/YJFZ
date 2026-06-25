import { AlertTriangle } from "lucide-react";

const PASS_LABELS = { excellent: "优秀", good: "良好", pass: "合格", fail: "不合格" };
const PASS_COLORS = { excellent: "#16a34a", good: "#2563eb", pass: "#d97706", fail: "#dc2626" };

export default function TriageScoreCard({ score, onClose }) {
  if (!score) return null;

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center",
      background: "rgba(0,0,0,0.4)", animation: "fadeIn 0.2s",
    }}>
      <div style={{
        background: "#fff", borderRadius: 16, padding: 28, maxWidth: 560, width: "90%", maxHeight: "85vh",
        overflow: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
        animation: "scoreSlideUp 0.3s ease",
      }}>
        {/* 总分 */}
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <div style={{ fontSize: "3rem", fontWeight: 900, color: score.total_score >= 80 ? "#16a34a" : score.total_score >= 60 ? "#d97706" : "#dc2626" }}>
            {score.total_score}
          </div>
          <div style={{ fontSize: "0.85rem", color: "#6b7280" }}>总分 / {score.total_score > 100 ? "120" : "100"}</div>
          {score.pass_status && (
            <span style={{
              display: "inline-block", marginTop: 8, padding: "4px 16px", borderRadius: 20,
              fontSize: "0.85rem", fontWeight: 700, color: "#fff",
              background: PASS_COLORS[score.pass_status] || "#6b7280",
            }}>
              {PASS_LABELS[score.pass_status] || score.pass_status}
            </span>
          )}
        </div>

        {/* 严重错误 */}
        {score.severe_error_triggered && (
          <div style={{
            padding: 12, marginBottom: 16, borderRadius: 8, background: "#fef2f2", border: "1px solid #fecaca",
            display: "flex", gap: 8, alignItems: "flex-start",
          }}>
            <AlertTriangle size={20} color="#dc2626" style={{ flexShrink: 0 }} />
            <div>
              <div style={{ fontWeight: 700, color: "#dc2626", fontSize: "0.85rem", marginBottom: 4 }}>严重错误 — 一票否决</div>
              {(score.severe_errors || []).map((e, i) => (
                <div key={i} style={{ fontSize: "0.78rem", color: "#991b1b" }}>· {e.message || e}</div>
              ))}
            </div>
          </div>
        )}

        {/* 标准答案 */}
        {score.standard_answer && (
          <div style={{ marginBottom: 16, padding: 12, background: "#f8fafc", borderRadius: 8, fontSize: "0.8rem" }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>标准分诊</div>
            <div>等级：{score.standard_answer.triage_level || "—"}</div>
            <div>区域：{score.standard_answer.triage_zone || "—"}</div>
          </div>
        )}

        {/* 分项评分 */}
        {score.detail_scores && Object.entries(score.detail_scores).map(([name, dim]) => (
          <div key={name} style={{ marginBottom: 10, fontSize: "0.8rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
              <span>{name}</span>
              <span style={{ fontWeight: 600 }}>{dim.score}/{dim.max}</span>
            </div>
            <div style={{ height: 5, borderRadius: 3, background: "#e5e7eb", overflow: "hidden" }}>
              <div style={{ height: "100%", borderRadius: 3, background: dim.score >= dim.max * 0.7 ? "#22c55e" : "#f59e0b", width: `${(dim.score / dim.max) * 100}%` }} />
            </div>
          </div>
        ))}

{/* V3: 规则依据 */}
        {score.rule_result && (
          <div style={{ marginBottom: 16, padding: 12, background: "#f8fafc", borderRadius: 8, fontSize: "0.78rem" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>规则引擎依据</div>
            <div style={{ display: "flex", gap: 12, marginBottom: 8 }}>
              <span>规则最低等级: <b>{score.rule_result.minimum_level_by_rules}</b></span>
              <span>ESI: {score.rule_result.esi_ctas_mapping?.esi || "-"}</span>
              <span>CTAS: {score.rule_result.esi_ctas_mapping?.ctas || "-"}</span>
            </div>
            {score.rule_result.under_triage && <div style={{ color: "#dc2626", marginBottom: 4 }}>⚠ 存在低估分诊风险</div>}
            {score.rule_result.over_triage && <div style={{ color: "#d97706", marginBottom: 4 }}>⚠ 存在过度分诊</div>}
            {(score.rule_result.rule_hits || []).slice(0, 5).map((h, i) => (
              <div key={i} style={{ padding: "4px 0", borderTop: "1px solid #e5e7eb", fontSize: "0.72rem" }}>
                <span style={{ fontWeight: 600 }}>{h.rule_id}</span>: {h.evidence?.substring(0, 80)}...
              </div>
            ))}
            {(score.rule_result.explanations || []).slice(0, 3).map((e, i) => (
              <div key={"ex"+i} style={{ padding: "4px 0", color: "#6b7280", fontSize: "0.72rem" }}>· {e}</div>
            ))}
          </div>
        )}

        <button onClick={onClose} style={{
          width: "100%", marginTop: 16, padding: "10px", borderRadius: 8, border: "none",
          background: "#2563eb", color: "#fff", fontSize: "0.9rem", fontWeight: 600, cursor: "pointer",
        }}>
          查看详细报告
        </button>
      </div>
    </div>
  );
}
