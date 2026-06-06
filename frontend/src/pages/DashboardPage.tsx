// frontend/src/pages/DashboardPage.tsx
import { useAuth } from "../auth/AuthContext";

export default function DashboardPage() {
  const { user, logout } = useAuth();
  return (
    <div className="page">
      <header className="topbar">
        <strong>Clinical Scribe</strong>
        <span>{user?.first_name} {user?.last_name} · {user?.role}</span>
        <button onClick={logout}>退出</button>
      </header>
      <main className="content">
        <h2>Welcome, {user?.first_name} </h2>
        <p>Here will be the Phase 2 clinical workspace (transcription input + streaming SOAP generation).</p>
        {user?.role === "admin" && <p>(You are an administrator, Phase 4 will have a management backend入口.)</p>}
      </main>
    </div>
  );
}