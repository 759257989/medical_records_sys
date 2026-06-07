// frontend/src/pages/DashboardPage.tsx
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="page">
      <header className="topbar">
        <strong>Clinical Scribe</strong>
        <span>{user?.first_name} {user?.last_name} · {user?.role}</span>
        <button onClick={logout}>Exit</button>
      </header>
      <main className="content">
        <h2>Welcome, {user?.first_name} </h2>
        <button className="primary" onClick={() => nav("/encounter")}>+ New Encounter (Enter Workspace)</button>
        {user?.role === "admin" && <p>(You are an administrator, Phase 4 will have a management backend入口.)</p>}
      </main>
    </div>
  );
}