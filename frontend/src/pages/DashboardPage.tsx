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

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [items, setItems] = useState<Enc[]>([]);

  useEffect(() => {
    api.get<Enc[]>("/encounters/mine").then((r) => setItems(r.data)).catch(() => {});
  }, []);

  const drafts = items.filter((e) => e.status !== "finalized");   // 未完成（可继续）
  const done = items.filter((e) => e.status === "finalized");      // 已完成（可查看/续写）

  const renderList = (list: Enc[], cta: string) => (
    <ul className="draft-list">
      {list.map((e) => (
        <li key={e.id}>
          <div>
            <strong>{e.patient_name}</strong> · {e.dob}
            <span className="badge">{e.status}</span>
            {e.version_count > 0 && <span className="badge">{e.version_count} 版本</span>}
          </div>
          <div className="muted">更新于 {new Date(e.updated_at).toLocaleString()}</div>
          <button onClick={() => nav(`/encounter?id=${e.id}`)}>{cta} →</button>
        </li>
      ))}
    </ul>
  );

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
        {drafts.length === 0 ? <p className="muted">没有未完成的草稿。</p> : renderList(drafts, "继续")}

        <h3 style={{ marginTop: 24 }}>已完成的就诊（可查看版本历史 / 续写）</h3>
        {done.length === 0 ? <p className="muted">还没有已完成的就诊。</p> : renderList(done, "打开")}

        {user?.role === "admin" && (
          <p style={{ marginTop: 24 }}>
            <button className="primary" onClick={() => nav("/admin")}>进入管理后台 →</button>
          </p>
        )}
      </main>
    </div>
  );
}
