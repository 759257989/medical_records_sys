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
  const [oldNo, setOldNo] = useState<number | null>(null);   // 基准（旧）
  const [newNo, setNewNo] = useState<number | null>(null);   // 对比（新）

  // 拉该就诊的全部版本（后端已按 version_no 倒序）；默认对比「次新 → 最新」
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
        <strong style={{ cursor: "pointer" }} onClick={() => nav(`/encounter?id=${encId}`)}>
          ← 返回就诊
        </strong>
        <span>{user?.first_name} {user?.last_name} · {user?.role}</span>
        <button onClick={logout}>退出</button>
      </header>
      <main className="content">
        <h2>版本对比</h2>

        {versions.length < 2 ? (
          <p className="muted">至少需要两个已保存版本才能对比。</p>
        ) : (
          <>
            <div className="filters">
              <label>基准（旧）</label>
              <select value={oldNo ?? ""} onChange={(e) => setOldNo(Number(e.target.value))}>
                {versions.map((v) => (
                  <option key={v.version_no} value={v.version_no}>
                    V{v.version_no} · {new Date(v.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
              <span>→</span>
              <label>对比（新）</label>
              <select value={newNo ?? ""} onChange={(e) => setNewNo(Number(e.target.value))}>
                {versions.map((v) => (
                  <option key={v.version_no} value={v.version_no}>
                    V{v.version_no} · {new Date(v.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
              <span className="diff-legend"><i className="del">删除</i> <i className="add">新增</i></span>
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