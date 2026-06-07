// frontend/src/pages/DashboardPage.tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import { useAuth } from "../auth/AuthContext";

type Draft = { id: string; patient_name: string; dob: string; status: string; updated_at: string };

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [drafts, setDrafts] = useState<Draft[]>([]);

  useEffect(() => {
    api.get<Draft[]>("/encounters/mine").then((r) => setDrafts(r.data)).catch(() => {});
  }, []);

  return (
    <div className="page">
      <header className="topbar">
        <strong>Clinical Scribe</strong>
        <span>{user?.first_name} {user?.last_name} · {user?.role}</span>
        <button onClick={logout}>退出</button>
      </header>
      <main className="content">
        <h2>Welcome, {user?.first_name}</h2>
        <button className="primary" onClick={() => nav("/encounter")}>+ 新建就诊</button>

        <h3 style={{ marginTop: 24 }}>未完成的就诊（可继续）</h3>
        {drafts.length === 0 && <p className="muted">没有未完成的草稿。</p>}
        <ul className="draft-list">
          {drafts.map((d) => (
            <li key={d.id}>
              <div>
                <strong>{d.patient_name}</strong> · {d.dob}
                <span className="badge">{d.status}</span>
              </div>
              <div className="muted">更新于 {new Date(d.updated_at).toLocaleString()}</div>
              <button onClick={() => nav(`/encounter?id=${d.id}`)}>继续 →</button>
            </li>
          ))}
        </ul>

        {user?.role === "admin" && <p className="muted">（你是管理员，Phase 4 将有管理后台入口。）</p>}
      </main>
    </div>
  );
}