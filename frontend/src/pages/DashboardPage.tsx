// frontend/src/pages/DashboardPage.tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import { useAuth } from "../auth/AuthContext";

type Enc = {
  id: string;
  patient_name: string;
  dob: string;
  status: string;
  updated_at: string;
  version_count: number;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  generated: "Generated",
  finalized: "Finalized",
};

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [items, setItems] = useState<Enc[]>([]);
  const [showCompleted, setShowCompleted] = useState(false);   // Completed section is foldable

  // Admins do not use the provider workspace — send them to the console.
  useEffect(() => {
    if (user?.role === "admin") nav("/admin", { replace: true });
  }, [user, nav]);

  useEffect(() => {
    api.get<Enc[]>("/encounters/mine").then((r) => setItems(r.data)).catch(() => {});
  }, []);

  const drafts = items.filter((e) => e.status !== "finalized");   // in progress
  const done = items.filter((e) => e.status === "finalized");      // completed

  const renderList = (list: Enc[], cta: string) => (
    <ul className="draft-list">
      {list.map((e) => (
        <li key={e.id}>
          <div className="patient">
            <strong>{e.patient_name}</strong> · DOB {e.dob}
            <span className={`badge ${e.status}`}>{STATUS_LABEL[e.status] ?? e.status}</span>
            {e.version_count > 0 && <span className="badge">{e.version_count} version{e.version_count > 1 ? "s" : ""}</span>}
          </div>
          <div className="meta">Updated {new Date(e.updated_at).toLocaleString()}</div>
          <button className="primary" onClick={() => nav(`/encounter?id=${e.id}`)}>{cta}</button>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="page">
      <header className="topbar">
        <img className="brand-logo" src="/mednotecopilot.png" alt="MedNote Copilot" onClick={() => nav("/")} />
        <span className="user">
          {user?.first_name} {user?.last_name}
          <span className="role">{user?.role}</span>
        </span>
        <button className="ghost" onClick={logout}>Sign out</button>
      </header>

      <main className="content">
        <div className="page-head">
          <h2>Welcome, {user?.first_name}</h2>
          <p>Create a new encounter or continue documenting an existing one.</p>
        </div>

        <button className="primary" onClick={() => nav("/encounter")}>New Encounter</button>

        {/* In progress — always visible */}
        <div className="section-toggle" style={{ cursor: "default" }}>
          In progress <span className="count">({drafts.length})</span>
        </div>
        {drafts.length === 0
          ? <div className="empty-state">No encounters in progress.</div>
          : renderList(drafts, "Continue")}

        {/* Completed — foldable */}
        <div className="section-toggle" onClick={() => setShowCompleted((v) => !v)}>
          <span className={`chevron ${showCompleted ? "open" : ""}`}>▶</span>
          Completed <span className="count">({done.length})</span>
        </div>
        {showCompleted && (
          done.length === 0
            ? <div className="empty-state">No completed encounters yet.</div>
            : renderList(done, "Open")
        )}
      </main>
    </div>
  );
}
