import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useState, lazy, Suspense } from "react";
import { ToastProvider } from "./components/Toast";
import { ConfirmProvider } from "./components/ui/ConfirmDialog";
import ErrorBoundary from "./components/ErrorBoundary";
import Login from "./pages/triage/Login";

const TriageCaseSelect = lazy(() => import("./pages/triage/TriageCaseSelect"));
const TriageTraining = lazy(() => import("./pages/triage/TriageTraining"));
const TriageDynamicTraining = lazy(() => import("./pages/triage/TriageDynamicTraining"));
const TriageRecordDetail = lazy(() => import("./pages/triage/TriageRecordDetail"));
const TriageAdmin = lazy(() => import("./pages/triage/TriageAdmin"));
const TriageTasks = lazy(() => import("./pages/triage/TriageTasks"));
const TriageLearningPath = lazy(() => import("./pages/triage/TriageLearningPath"));

const TRAINING_ROLES = ["student", "teacher", "reviewer", "admin"];

function ProtectedRoute({ children, role }) {
  const token = localStorage.getItem("token");
  const userRole = localStorage.getItem("userRole");
  if (!token) return <Navigate to="/login" replace />;
  if (role) {
    const allowed = Array.isArray(role) ? role : [role];
    if (!allowed.includes(userRole)) return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  const [user, setUser] = useState(() => {
    const u = localStorage.getItem("user");
    return u ? JSON.parse(u) : null;
  });

  const handleLogin = (userData) => {
    const normalizedUser = {
      ...userData,
      id: userData.id ?? userData.user_id,
    };
    localStorage.setItem("token", userData.access_token);
    localStorage.setItem("userRole", normalizedUser.role);
    localStorage.setItem("user", JSON.stringify(normalizedUser));
    setUser(normalizedUser);
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("userRole");
    localStorage.removeItem("user");
    setUser(null);
  };

  return (
    <ErrorBoundary>
      <ToastProvider>
        <ConfirmProvider>
          <BrowserRouter>
            <Suspense fallback={<div style={{ padding: 40, textAlign: "center" }}>加载中...</div>}>
              <Routes>
                <Route path="/login" element={user ? <Navigate to="/triage" replace /> : <Login onLogin={handleLogin} />} />
                <Route path="/triage" element={<ProtectedRoute><TriageCaseSelect user={user} onLogout={handleLogout} /></ProtectedRoute>} />
                <Route path="/triage/training/start" element={<ProtectedRoute role={TRAINING_ROLES}><TriageTraining /></ProtectedRoute>} />
                <Route path="/triage/dynamic/start" element={<ProtectedRoute role={TRAINING_ROLES}><TriageDynamicTraining /></ProtectedRoute>} />
                <Route path="/triage/dynamic/:recordId" element={<ProtectedRoute role={TRAINING_ROLES}><TriageDynamicTraining /></ProtectedRoute>} />
                <Route path="/triage/record/:id" element={<ProtectedRoute><TriageRecordDetail user={user} onLogout={handleLogout} /></ProtectedRoute>} />
                <Route path="/triage/admin" element={<ProtectedRoute role={["teacher", "reviewer", "admin"]}><TriageAdmin user={user} onLogout={handleLogout} /></ProtectedRoute>} />
                <Route path="/triage/tasks" element={<ProtectedRoute role="student"><TriageTasks user={user} onLogout={handleLogout} /></ProtectedRoute>} />
                <Route path="/triage/learning-path" element={<ProtectedRoute><TriageLearningPath user={user} onLogout={handleLogout} /></ProtectedRoute>} />
                <Route path="/" element={<Navigate to="/triage" replace />} />
                <Route path="*" element={<Navigate to="/login" replace />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </ConfirmProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
