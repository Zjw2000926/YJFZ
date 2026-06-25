import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../../components/Layout";
import PageHeader from "../../components/ui/PageHeader";
import Card from "../../components/ui/Card";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import LoadingState from "../../components/ui/LoadingState";
import EmptyState from "../../components/ui/EmptyState";
import { useToast } from "../../components/useToast";
import { getTriageLearningPath } from "../../api";
import { BookOpen, AlertTriangle } from "lucide-react";

export default function TriageLearningPath({ user, onLogout }) {
  const [path, setPath] = useState(null);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line no-unused-vars
  const toast = useToast();
  const navigate = useNavigate();

  useEffect(() => {
    getTriageLearningPath(user?.id).then(r => setPath(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, [user]);

  if (loading) return <Layout user={user} onLogout={onLogout}><LoadingState /></Layout>;
  if (!path) return <Layout user={user} onLogout={onLogout}><EmptyState title="暂无学习路径" description="完成更多训练后系统将自动生成个性化学习路径" /></Layout>;

  const profile = path.profile_snapshot?.summary || {};

  return (
    <Layout user={user} onLogout={onLogout}>
      <PageHeader title="个性化学习路径" subtitle="基于你的训练数据自动推荐" icon={BookOpen} backTo="/triage" />

      <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: 10, marginBottom: 16, fontSize: "0.75rem", color: "#991b1b" }}>
        ⚠ 仅用于教学训练，不用于真实临床分诊。
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10, marginBottom: 20 }}>
        <Card><div style={{ textAlign: "center", fontSize: "0.75rem" }}>总训练<br/><b style={{ fontSize: "1.5rem" }}>{profile.total_records || 0}</b></div></Card>
        <Card><div style={{ textAlign: "center", fontSize: "0.75rem" }}>平均分<br/><b style={{ fontSize: "1.5rem", color: "#2563eb" }}>{profile.avg_score || "-"}</b></div></Card>
        <Card><div style={{ textAlign: "center", fontSize: "0.75rem" }}>准确率<br/><b style={{ fontSize: "1.5rem", color: "#16a34a" }}>{Math.round((profile.triage_accuracy || 0) * 100)}%</b></div></Card>
        <Card><div style={{ textAlign: "center", fontSize: "0.75rem" }}>低估率<br/><b style={{ fontSize: "1.5rem", color: "#dc2626" }}>{Math.round((profile.under_triage_rate || 0) * 100)}%</b></div></Card>
      </div>

      <Card title="推荐训练">
        {(path.recommendations || []).length > 0 ? (
          path.recommendations.map((rec, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: "1px solid #f3f4f6" }}>
              <Badge variant={rec.priority === 1 ? "danger" : "warning"}>P{rec.priority}</Badge>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{rec.type === "category" ? "病例类别训练" : rec.type === "rule" ? "规则能力训练" : "知识学习"}</div>
                <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{rec.reason}</div>
              </div>
              <Button size="sm" onClick={() => navigate("/triage")}>去训练 →</Button>
            </div>
          ))
        ) : <EmptyState title="暂无推荐" description="完成更多训练后系统将分析你的薄弱环节" />}
      </Card>

      {path.profile_snapshot?.weaknesses?.length > 0 && (
        <Card title="薄弱环节" style={{ marginTop: 12 }}>
          {path.profile_snapshot.weaknesses.map((w, i) => (
            <div key={i} style={{ padding: "4px 0", fontSize: "0.8rem" }}>
              <AlertTriangle size={12} color="#d97706" /> {w.label} (缺失率: {Math.round(w.miss_rate * 100)}%)
            </div>
          ))}
        </Card>
      )}
    </Layout>
  );
}
