// frontend/src/pages/DiffPage.tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { diffWords } from "../lib/diff";

type Version = {
  version_no: number; created_at: string; author_name: string;
  subjective: string; objective: string; assessment: string; plan: string;
};

const SECTIONS: { key: keyof Version; label: string }[] = [
  { key: "subjective", label: "S — Subjective" },
  { key: "objective", label: "O — Objective" },
  { key: "assessment", label: "A — Assessment" },
  { key: "plan", label: "P — Plan" },
];

export default function DiffPage() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const encId = params.get("id");

  const [versions, setVersions] = useState<Version[]>([]);
  const [oldNo, setOldNo] = useState<number | null>(null);   // base (older)
  const [newNo, setNewNo] = useState<number | null>(null);   // compare (newer)

  // Load all versions (backend returns them in descending order); default: previous → latest
  useEffect(() => {
    if (!encId) return;
    api.get<Version[]>(`/encounters/${encId}/notes`).then((r) => {
      const vs = r.data;
      setVersions(vs);
      if (vs.length >= 2) { setNewNo(vs[0].version_no); setOldNo(vs[1].version_no); }
      else if (vs.length === 1) { setNewNo(vs[0].version_no); setOldNo(vs[0].version_no); }
    }).catch(() => {});
  }, [encId]);

  const oldV = useMemo(() => versions.find((v) => v.version_no === oldNo) || null, [versions, oldNo]);
  const newV = useMemo(() => versions.find((v) => v.version_no === newNo) || null, [versions, newNo]);

  return (
    <div className="page">
      <header className="topbar">
        <img className="brand-logo" src="/mednotecopilot.png" alt="MedNote Copilot" onClick={() => nav("/")} />
        <button className="ghost" onClick={() => nav(`/encounter?id=${encId}`)}>Back to Encounter</button>
        <span className="user">
          {user?.first_name} {user?.last_name}
          <span className="role">{user?.role}</span>
        </span>
        <button className="ghost" onClick={logout}>Sign out</button>
      </header>
      <main className="content">
        <div className="page-head">
          <h2>Compare Versions</h2>
          <p>Review what changed between two saved versions of this note.</p>
        </div>

        {versions.length < 2 ? (
          <div className="empty-state">At least two saved versions are required to compare.</div>
        ) : (
          <>
            <div className="filters">
              <label>Base (older)</label>
              <select value={oldNo ?? ""} onChange={(e) => setOldNo(Number(e.target.value))}>
                {versions.map((v) => (
                  <option key={v.version_no} value={v.version_no}>
                    Version {v.version_no} · {new Date(v.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
              <label>Compare (newer)</label>
              <select value={newNo ?? ""} onChange={(e) => setNewNo(Number(e.target.value))}>
                {versions.map((v) => (
                  <option key={v.version_no} value={v.version_no}>
                    Version {v.version_no} · {new Date(v.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
              <span className="diff-legend"><i className="del">Removed</i> <i className="add">Added</i></span>
            </div>

            {oldV && newV && SECTIONS.map((s) => (
              <div className="diff-section" key={s.key as string}>
                <h4>{s.label}</h4>
                <p className="diff">
                  {diffWords(String(oldV[s.key] || ""), String(newV[s.key] || "")).map((part, i) => (
                    <span key={i} className={part.type}>{part.value}</span>
                  ))}
                </p>
              </div>
            ))}
          </>
        )}
      </main>
    </div>
  );
}
