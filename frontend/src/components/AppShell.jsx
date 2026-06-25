import { NavLink, useNavigate } from "react-router-dom";
import { ClipboardList, Target, Users, BarChart3 } from "lucide-react";

const studentLinks = [
  { to: "/triage", icon: ClipboardList, label: "病例训练" },
  { to: "/triage/tasks", icon: Target, label: "我的任务" },
];

const teacherLinks = [
  { to: "/triage/admin", icon: Users, label: "教师管理" },
  { to: "/triage/admin?tab=cohorts", icon: Target, label: "班级与任务" },
  { to: "/triage/admin?tab=stats", icon: BarChart3, label: "数据分析" },
];

export default function AppShell({ children, user, onLogout }) {
  const navigate = useNavigate();
  const isTeacher = user?.role === "teacher";
  const links = isTeacher ? teacherLinks : studentLinks;

  const handleLogout = () => {
    onLogout();
    navigate("/login");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h2>预检分诊训练系统</h2>
          <span>仅用于教学训练</span>
        </div>

        <nav className="sidebar-nav">
          {links.map((link) => {
            const Icon = link.icon;
            return (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/triage"}
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
            >
              <Icon className="nav-icon" size={16} />
              {link.label}
            </NavLink>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-user">
            <div className="avatar-dot">
              {(user?.display_name || "U")[0]}
            </div>
            <div className="info">
              <div className="name">{user?.display_name}</div>
              <div className="role">{isTeacher ? "教师" : "学生"}</div>
            </div>
          </div>
          <button className="btn-logout" onClick={handleLogout}>
            退出登录
          </button>
        </div>
      </aside>

      <main className="main-content">
        {children}
      </main>
    </div>
  );
}
