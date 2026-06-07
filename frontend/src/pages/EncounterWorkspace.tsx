// frontend/src/pages/EncounterWorkspace.tsx
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../api/client";
import { streamSoap } from "../api/stream";
import { EMPTY_SOAP, parseSoap, type Soap } from "../lib/soap";
import { useAuth } from "../auth/AuthContext";

type Template = { id: string; name: string; encounter_type: string | null };
type Patient = { first_name: string; last_name: string; dob: string };
type Encounter = { id: string; is_returning: boolean; patient: Patient };
type Version = { version_no: number; created_at: string; author_name: string } & Soap;
type IcdHit = { code: string; description: string; score: number | null };

export default function EncounterWorkspace() {
  const { user, logout } = useAuth();
  const [params] = useSearchParams();
  const resumeId = params.get("id");   // 带 ?id= 表示恢复某条草稿
  const nav = useNavigate();

  const [templates, setTemplates] = useState<Template[]>([]);
  const [form, setForm] = useState({ first_name: "", last_name: "", dob: "", template_id: "" });

  const [encounter, setEncounter] = useState<Encounter | null>(null);
  const [transcript, setTranscript] = useState("");
  const [soap, setSoap] = useState<Soap>(EMPTY_SOAP);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [versions, setVersions] = useState<Version[]>([]);
  const [toast, setToast] = useState("");
  const [toolNotice, setToolNotice] = useState("");   // 历史注入提示
  const [draftSaved, setDraftSaved] = useState("");    // 草稿保存时间

  // ICD 搜索
  const [icdQuery, setIcdQuery] = useState("");
  const [icdHits, setIcdHits] = useState<IcdHit[]>([]);

  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(""), 2500); };

  // 进页面拉模板
  useEffect(() => {
    api.get<Template[]>("/templates").then((r) => setTemplates(r.data)).catch(() => {});
  }, []);

  // 恢复就诊（?id=）：草稿回填编辑区；若已完成且草稿为空，则回填最新保存版本
  useEffect(() => {
    if (!resumeId) return;
    api.get(`/encounters/${resumeId}`).then(async (r) => {
      const e = r.data;
      setEncounter({ id: e.id, is_returning: e.is_returning, patient: e.patient });
      setTranscript(e.transcript || "");
      const wn = e.working_note || {};
      const wnSoap: Soap = {
        subjective: wn.subjective || "", objective: wn.objective || "",
        assessment: wn.assessment || "", plan: wn.plan || "",
      };
      const vr = await api.get<Version[]>(`/encounters/${e.id}/notes`);
      setVersions(vr.data);
      const empty = !wnSoap.subjective && !wnSoap.objective && !wnSoap.assessment && !wnSoap.plan;
      if (empty && vr.data.length > 0) {
        const v = vr.data[0];   // 最新版本（列表按版本号倒序）
        setSoap({
          subjective: v.subjective || "", objective: v.objective || "",
          assessment: v.assessment || "", plan: v.plan || "",
        });
      } else {
        setSoap(wnSoap);
      }
    }).catch(() => flash("无法恢复该就诊"));
  }, [resumeId]);

  // 草稿 autosave：transcript/soap 变化后防抖 1s 存服务端（生成中不存）
  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (!encounter || generating) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      api.put(`/encounters/${encounter.id}/draft`, { transcript, working_note: soap })
        .then(() => setDraftSaved(new Date().toLocaleTimeString()))
        .catch(() => {});
    }, 1000);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [transcript, soap, encounter, generating]);

  // ICD 搜索：防抖 350ms
  useEffect(() => {
    const q = icdQuery.trim();
    if (!q) { setIcdHits([]); return; }
    const t = window.setTimeout(() => {
      api.get<IcdHit[]>("/icd10/search", { params: { q } })
        .then((r) => setIcdHits(r.data)).catch(() => setIcdHits([]));
    }, 350);
    return () => clearTimeout(t);
  }, [icdQuery]);

  const startEncounter = async (e: React.FormEvent) => {
    e.preventDefault();
    const body = { ...form, template_id: form.template_id || null };
    const r = await api.post<Encounter>("/encounters", body);
    setEncounter(r.data); setSoap(EMPTY_SOAP); setVersions([]); setTranscript("");
  };

  const generate = async () => {
    if (!encounter || !transcript.trim()) return;
    setGenerating(true); setSoap(EMPTY_SOAP); setToolNotice("");
    try {
      await streamSoap(encounter.id, transcript, {
        onText: (full) => setSoap(parseSoap(full)),
        onTool: (label) => setToolNotice(label),
      });
    } catch (err) {
      flash("生成失败：" + (err as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const save = async () => {
    if (!encounter) return;
    setSaving(true);
    try {
      const r = await api.post(`/encounters/${encounter.id}/notes`, soap);
      flash(`已保存 V${r.data.version_no}`);
      await fetchVersions(encounter.id);
    } catch {
      flash("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const fetchVersions = async (id: string) => {
    const r = await api.get<Version[]>(`/encounters/${id}/notes`);
    setVersions(r.data);
  };

  const viewVersion = (v: Version) =>
    setSoap({ subjective: v.subjective, objective: v.objective, assessment: v.assessment, plan: v.plan });

  const appendIcd = (hit: IcdHit) =>
    setSoap((s) => ({
      ...s,
      assessment: (s.assessment ? s.assessment + "\n" : "") + `- ${hit.code}: ${hit.description}`,
    }));

  // ── 未建/未恢复就诊：表单 ──
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

  const p = encounter.patient;
  return (
    <div className="page">
      <Topbar user={user} logout={logout} />
      {toast && <div className="toast">{toast}</div>}
      <main className="workspace">
        {/* 左栏：转录 */}
        <section className="panel">
          <div className="panel-head">
            <h3>转录 / 临床观察</h3>
            <span className="patient-chip">
              {p.first_name} {p.last_name} · {p.dob}
              {encounter.is_returning && <em className="returning"> 复诊</em>}
            </span>
          </div>
          <textarea className="transcript" rows={16} placeholder="粘贴就诊转录或自由书写临床观察…"
            value={transcript} onChange={(e) => setTranscript(e.target.value)} />
          <div className="row-between">
            <button className="primary" disabled={generating || !transcript.trim()} onClick={generate}>
              {generating ? "生成中…" : "Generate Note"}
            </button>
            {draftSaved && <span className="muted">草稿已保存 {draftSaved}</span>}
          </div>
        </section>

        {/* 中栏：SOAP + ICD 控件 */}
        <section className="panel">
          <div className="panel-head">
            <h3>SOAP 笔记</h3>
            <button className="primary" disabled={saving} onClick={save}>
              {saving ? "保存中…" : "Save"}
            </button>
          </div>

          {toolNotice && <div className="tool-notice">🔍 {toolNotice}（已注入既往史）</div>}

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

          {/* ICD-10 搜索控件 */}
          <div className="icd">
            <label>ICD-10 搜索（输入英文症状/诊断）</label>
            <input placeholder="e.g. shortness of breath on exertion"
              value={icdQuery} onChange={(e) => setIcdQuery(e.target.value)} />
            {icdHits.length > 0 && (
              <ul className="icd-hits">
                {icdHits.map((h) => (
                  <li key={h.code} onClick={() => appendIcd(h)} title="点击加入 Assessment">
                    <code>{h.code}</code>
                    <span>{h.description}</span>
                    {h.score != null && <em>{h.score}</em>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* 右栏：版本历史 */}
         <aside className="panel narrow">
          <div className="panel-head">
            <h3>版本历史</h3>
            {versions.length >= 2 && (
              <button onClick={() => nav(`/diff?id=${encounter.id}`)}>对比</button>
            )}
          </div>
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

function SoapBox({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="soap-box">
      <label>{label}</label>
      <textarea rows={5} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}