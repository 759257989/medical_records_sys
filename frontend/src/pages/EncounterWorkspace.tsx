// frontend/src/pages/EncounterWorkspace.tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import { streamSoap } from "../api/stream";
import { EMPTY_SOAP, parseSoap, type Soap } from "../lib/soap";
import { useAuth } from "../auth/AuthContext";

type Template = { id: string; name: string; encounter_type: string | null };
type Encounter = { id: string; is_returning: boolean; patient: { first_name: string; last_name: string; dob: string } };
type Version = { version_no: number; created_at: string; author_name: string } & Soap;

export default function EncounterWorkspace() {
  const { user, logout } = useAuth();

  // ── 步骤1：新建就诊表单 ──
  const [templates, setTemplates] = useState<Template[]>([]);
  const [form, setForm] = useState({ first_name: "", last_name: "", dob: "", template_id: "" });

  // ── 步骤2：工作区状态 ──
  const [encounter, setEncounter] = useState<Encounter | null>(null);
  const [transcript, setTranscript] = useState("");
  const [soap, setSoap] = useState<Soap>(EMPTY_SOAP);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [versions, setVersions] = useState<Version[]>([]);
  const [toast, setToast] = useState("");

  // 进页面先拉模板列表
  useEffect(() => {
    api.get<Template[]>("/templates").then((r) => setTemplates(r.data)).catch(() => {});
  }, []);

  const flash = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 2500); };

  // 新建就诊
  const startEncounter = async (e: React.FormEvent) => {
    e.preventDefault();
    const body = { ...form, template_id: form.template_id || null };
    const r = await api.post<Encounter>("/encounters", body);
    setEncounter(r.data);
    setSoap(EMPTY_SOAP);
    setVersions([]);
  };

  // 生成 SOAP（流式）
  const generate = async () => {
    if (!encounter || !transcript.trim()) return;
    setGenerating(true);
    setSoap(EMPTY_SOAP);
    try {
      await streamSoap(encounter.id, transcript, (full) => setSoap(parseSoap(full)));
    } catch (err) {
      flash("生成失败：" + (err as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  // 保存版本
  const save = async () => {
    if (!encounter) return;
    setSaving(true);
    try {
      const r = await api.post(`/encounters/${encounter.id}/notes`, soap);
      flash(`已保存 V${r.data.version_no}`);
      await loadVersions();
    } catch {
      flash("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const loadVersions = async () => {
    if (!encounter) return;
    const r = await api.get<Version[]>(`/encounters/${encounter.id}/notes`);
    setVersions(r.data);
  };

  // 点历史版本 → 载入编辑区查看
  const viewVersion = (v: Version) =>
    setSoap({ subjective: v.subjective, objective: v.objective, assessment: v.assessment, plan: v.plan });

  // ── 渲染：未建就诊时显示表单 ──
  if (!encounter) {
    return (
      <div className="page">
        <Topbar user={user} logout={logout} />
        <main className="content">
          <form className="card wide" onSubmit={startEncounter}>
            <h2>新建就诊</h2>
            <div className="row">
              <input required placeholder="名 First name"
                value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
              <input required placeholder="姓 Last name"
                value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
              <input required type="date"
                value={form.dob} onChange={(e) => setForm({ ...form, dob: e.target.value })} />
            </div>
            <select value={form.template_id} onChange={(e) => setForm({ ...form, template_id: e.target.value })}>
              <option value="">（不使用模板 / General）</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <button type="submit">开始就诊 →</button>
          </form>
        </main>
      </div>
    );
  }

  // ── 渲染：工作区 ──
  const p = encounter.patient;
  return (
    <div className="page">
      <Topbar user={user} logout={logout} />
      {toast && <div className="toast">{toast}</div>}
      <main className="workspace">
        {/* 左栏：转录输入 */}
        <section className="panel">
          <div className="panel-head">
            <h3>转录 / 临床观察</h3>
            <span className="patient-chip">
              {p.first_name} {p.last_name} · {p.dob}
              {encounter.is_returning && <em className="returning"> 复诊</em>}
            </span>
          </div>
          <textarea className="transcript" rows={18} placeholder="粘贴就诊转录或自由书写临床观察…"
            value={transcript} onChange={(e) => setTranscript(e.target.value)} />
          <button className="primary" disabled={generating || !transcript.trim()} onClick={generate}>
            {generating ? "生成中…" : "Generate Note"}
          </button>
        </section>

        {/* 中栏：SOAP 编辑区 */}
        <section className="panel">
          <div className="panel-head">
            <h3>SOAP 笔记</h3>
            <button className="primary" disabled={saving} onClick={save}>
              {saving ? "保存中…" : "Save"}
            </button>
          </div>

          {soap.insufficient ? (
            <div className="insufficient">⚠️ 转录中未发现足够的临床信息：{soap.insufficient}</div>
          ) : (
            <div className="soap">
              <SoapBox label="S — Subjective" value={soap.subjective}
                onChange={(v) => setSoap({ ...soap, subjective: v })} />
              <SoapBox label="O — Objective" value={soap.objective}
                onChange={(v) => setSoap({ ...soap, objective: v })} />
              <SoapBox label="A — Assessment（含 ICD-10）" value={soap.assessment}
                onChange={(v) => setSoap({ ...soap, assessment: v })} />
              <SoapBox label="P — Plan" value={soap.plan}
                onChange={(v) => setSoap({ ...soap, plan: v })} />
            </div>
          )}
        </section>

        {/* 右栏：版本历史 */}
        <aside className="panel narrow">
          <div className="panel-head"><h3>版本历史</h3></div>
          {versions.length === 0 && <p className="muted">尚无保存版本</p>}
          <ul className="versions">
            {versions.map((v) => (
              <li key={v.version_no} onClick={() => viewVersion(v)}>
                <strong>V{v.version_no}</strong>
                <span>{v.author_name}</span>
                <time>{new Date(v.created_at).toLocaleString()}</time>
              </li>
            ))}
          </ul>
        </aside>
      </main>
    </div>
  );
}

// 顶栏（复用 Dashboard 同款）
function Topbar({ user, logout }: { user: any; logout: () => void }) {
  const nav = useNavigate();
  return (
    <header className="topbar">
      <strong style={{ cursor: "pointer" }} onClick={() => nav("/")}>Clinical Scribe</strong>
      <span>{user?.first_name} {user?.last_name} · {user?.role}</span>
      <button onClick={logout}>退出</button>
    </header>
  );
}

// 单个可编辑 SOAP 分区
function SoapBox({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="soap-box">
      <label>{label}</label>
      <textarea rows={5} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}