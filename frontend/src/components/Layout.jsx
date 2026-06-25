import { useNavigate, useLocation } from "react-router-dom";
import { ClipboardList, Users, Target, LogOut, ShieldCheck } from "lucide-react";

const NAV_ITEMS = [
  { path: "/triage", label: "病例训练", icon: ClipboardList, roles: ["student", "teacher", "admin"] },
  { path: "/triage/tasks", label: "我的任务", icon: Target, roles: ["student"] },
  { path: "/triage/admin", label: "教师管理", icon: Users, roles: ["teacher", "admin"] },
  { path: "/triage/admin", label: "病例审核", icon: ShieldCheck, roles: ["reviewer"] },
];

export default function Layout({ user, onLogout, children }) {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      {/* Sidebar */}
      <div style={{
        width: 220, background: "#1e293b", color: "#e2e8f0", display: "flex", flexDirection: "column",
        position: "fixed", top: 0, left: 0, bottom: 0, zIndex: 100,
      }}>
        <div style={{ padding: "20px 16px", borderBottom: "1px solid #334155" }}>
          <div style={{ fontSize: "1rem", fontWeight: 700, color: "#fff" }}>预检分诊训练系统</div>
          <div style={{ fontSize: "0.65rem", color: "#94a3b8", marginTop: 2 }}>仅用于教学训练</div>
        </div>

        <nav style={{ flex: 1, padding: "12px 8px" }}>
          {NAV_ITEMS.filter(item => item.roles.includes(user?.role || "student")).map(item => {
            const active = location.pathname === item.path || location.pathname.startsWith(item.path + "/");
            return (
              <div key={item.path} onClick={() => navigate(item.path)} style={{
                display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", marginBottom: 2,
                borderRadius: 8, cursor: "pointer", fontSize: "0.85rem", fontWeight: active ? 600 : 400,
                background: active ? "#2563eb" : "transparent", color: active ? "#fff" : "#cbd5e1",
                transition: "all 0.15s",
              }}>
                <item.icon size={18} />
                <span>{item.label}</span>
              </div>
            );
          })}
        </nav>

        <div style={{ padding: "12px 16px", borderTop: "1px solid #334155", display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 600 }}>{user?.display_name || "用户"}</div>
            <div style={{ fontSize: "0.65rem", color: "#94a3b8" }}>{user?.role === "teacher" ? "教师" : user?.role === "reviewer" ? "审核员" : user?.role === "admin" ? "管理员" : "学生"}</div>
          </div>
          <LogOut size={16} style={{ cursor: "pointer", color: "#94a3b8" }} onClick={onLogout} />
        </div>
      </div>

      {/* Main content */}
      <div style={{ marginLeft: 220, flex: 1, background: "#f8fafc", minHeight: "100vh" }}>
        <div style={{ padding: "24px 28px" }}>
          {children}
        </div>
      </div>
    </div>
  );
}
