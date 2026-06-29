import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getTriageCases } from "../../api";
import Layout from "../../components/Layout";
import PageHeader from "../../components/ui/PageHeader";
import Card from "../../components/ui/Card";
import Badge from "../../components/ui/Badge";
import LoadingState from "../../components/ui/LoadingState";
import EmptyState from "../../components/ui/EmptyState";
import { useToast } from "../../components/useToast";
import { ClipboardList, Clock, Star } from "lucide-react";

const DIFFICULTY_LABELS = { 1: "初级", 2: "中级", 3: "高级" };
const DIFFICULTY_COLORS = { 1: "success", 2: "warning", 3: "danger" };

export default function TriageCaseSelect({ user, onLogout }) {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const navigate = useNavigate();
  const toast = useToast();

  useEffect(() => {
    getTriageCases()
      .then(({ data }) => setCases(data.items || []))
      .catch(() => toast.error("加载病例列表失败"))
      .finally(() => setLoading(false));
  }, [toast]);

  const filtered = filter === "all" ? cases : cases.filter((c) => c.difficulty === parseInt(filter));

  if (loading) return <Layout user={user} onLogout={onLogout}><LoadingState message="加载病例中..." /></Layout>;

  return (
    <Layout user={user} onLogout={onLogout}>
      <PageHeader
        title="预检分诊训练"
        subtitle="选择病例开始分诊训练"
        icon={ClipboardList}
      />

      {/* 难度筛选 */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {["all", "1", "2", "3"].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: "6px 16px", borderRadius: 20, border: filter === f ? "2px solid #2563eb" : "1px solid #d1d5db",
              background: filter === f ? "#eff6ff" : "#fff", color: filter === f ? "#2563eb" : "#6b7280",
              fontSize: "0.78rem", fontWeight: 500, cursor: "pointer",
            }}
          >
            {f === "all" ? "全部难度" : `${DIFFICULTY_LABELS[f]}难度`}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon={ClipboardList} title="暂无病例" />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
          {filtered.map((c) => (
            <div key={c.external_id} style={{ cursor: "pointer" }}
              onClick={() => {
                navigate(`/triage/training/start?case=${c.external_id}`);
              }}>
              <Card>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
                <h3 style={{ fontSize: "0.95rem", fontWeight: 700, flex: 1 }}>{c.display_name}</h3>
                <Badge variant={DIFFICULTY_COLORS[c.difficulty] || "neutral"}>
                  {DIFFICULTY_LABELS[c.difficulty] || "初级"}
                </Badge>
              </div>
              {c.initial_exposure?.chief_complaint && (
                <p style={{ fontSize: "0.8rem", color: "#6b7280", marginBottom: 8 }}>
                  主诉：{c.initial_exposure.chief_complaint}
                </p>
              )}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
                {(c.training_focus || []).slice(0, 3).map((f, i) => (
                  <span key={i} style={{ fontSize: "0.7rem", background: "#f3f4f6", padding: "2px 8px", borderRadius: 10 }}>{f}</span>
                ))}
              </div>
              <div style={{ display: "flex", gap: 16, fontSize: "0.72rem", color: "#9ca3af" }}>
                <span><Clock size={12} style={{ marginRight: 4 }} />预计5-8分钟</span>
                <span><Star size={12} style={{ marginRight: 4 }} />{c.patient_profile?.age}岁 {c.patient_profile?.gender}</span>
              </div>
            </Card>
            </div>
          ))}
        </div>
      )}
    </Layout>
  );
}
