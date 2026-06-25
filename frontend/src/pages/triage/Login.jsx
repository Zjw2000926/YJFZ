import { useState } from "react";
import axios from "axios";

const api = axios.create({ baseURL: "/api", timeout: 30000 });

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const { data } = await api.post("/auth/login", { username, password });
      onLogin(data);
    } catch (err) {
      setError(err?.response?.data?.detail || "登录失败");
    }
  };

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "100vh", background: "#f0f4f8" }}>
      <div style={{ background: "#fff", borderRadius: 16, padding: 40, width: 360, boxShadow: "0 4px 24px rgba(0,0,0,0.1)" }}>
        <h1 style={{ textAlign: "center", fontSize: "1.5rem", fontWeight: 700, marginBottom: 8 }}>预检分诊训练系统</h1>
        <p style={{ textAlign: "center", color: "#6b7280", fontSize: "0.85rem", marginBottom: 24 }}>仅用于教学训练，不用于真实临床分诊</p>
        {error && <div style={{ padding: 8, marginBottom: 12, background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 6, color: "#dc2626", fontSize: "0.8rem" }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 12 }}>
            <input value={username} onChange={e => setUsername(e.target.value)} placeholder="用户名" autoFocus
              style={{ width: "100%", padding: "10px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.9rem" }} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="密码"
              style={{ width: "100%", padding: "10px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.9rem" }} />
          </div>
          <button type="submit" style={{ width: "100%", padding: "10px", borderRadius: 8, border: "none", background: "#2563eb", color: "#fff", fontSize: "0.95rem", fontWeight: 600, cursor: "pointer" }}>
            登录
          </button>
        </form>
        <div style={{ marginTop: 16, fontSize: "0.72rem", color: "#9ca3af", textAlign: "center" }}>
          默认: admin/admin123 (教师) | student1/123456 (学生)
        </div>
      </div>
    </div>
  );
}
