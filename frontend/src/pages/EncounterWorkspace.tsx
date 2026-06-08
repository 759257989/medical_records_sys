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
  const resumeId = params.get("id");   // ?id= means resume an existing encounter
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
  const [toolNotice, setToolNotice] = useState("");      // prior-history injection notice
  const [draftSaved, setDraftSaved] = useState("");       // last autosave time
  const [savedOk, setSavedOk] = useState(false);          // post-save confirmation

  // ICD search
  const [icdQuery, setIcdQuery] = useState("");
  const [icdHits, setIcdHits] = useState<IcdHit[]>([]);

  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(""), 2500); };

  // Load templates on mount
  useEffect(() => {
    api.get<Template[]>("/templates").then((r) => setTemplates(r.data)).catch(() => {});
  }, []);

  // Resume encounter (?id=): restore draft; if finalized and draft empty, load latest saved version
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
        const v = vr.data[0];   // latest version (list is in descending order)
        setSoap({
          subjective: v.subjective || "", objective: v.objective || "",
          assessment: v.assessment || "", plan: v.plan || "",
        });
      } else {
        setSoap(wnSoap);
      }
    }).catch(() => flash("Could not load this encounter"));
  }, [resumeId]);

  // Draft autosave: debounce 1s after transcript/soap changes (skip while generating)
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

  // Clear the post-save confirmation once the provider edits the note again
  useEffect(() => { setSavedOk(false); }, [soap, transcript]);

  // ICD search: debounce 350ms
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
      flash("Generation failed: " + (err as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const save = async () => {
    if (!encounter) return;
    setSaving(true);
    try {
      await api.post(`/encounters/${encounter.id}/notes`, soap);
      setSavedOk(true);
      await fetchVersions(encounter.id);
    } catch {
      flash("Save failed");
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

  // A note may only be saved when it has real clinical content
  const noteEmpty =
    !soap.subjective?.trim() && !soap.objective?.trim() &&
    !soap.assessment?.trim() && !soap.plan?.trim();
  const canSave = !saving && !noteEmpty && !soap.insufficient;

  // ── New encounter form (before an encounter is created/resumed) ──
  if (!encounter) {
    return (
      <div className="page">
        <Topbar user={user} logout={logout} />
        <main className="content">
          <form className="card wide" onSubmit={startEncounter}>
            <h2>New Encounter</h2>
            <p className="hint">Enter patient details to begin. Returning patients are matched automatically.</p>
            <div className="row">
              <input required placeholder="First name"
                value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
              <input required placeholder="Last name"
                value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
              <input required type="date" title="Date of birth"
                value={form.dob} onChange={(e) => setForm({ ...form, dob: e.target.value })} />
            </div>
            <label className="field">Note template</label>
            <select value={form.template_id} onChange={(e) => setForm({ ...form, template_id: e.target.value })}>
              <option value="">General SOAP (default)</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <button className="primary" type="submit">Start Encounter</button>
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

      {/* Patient context bar */}
      <div className="patient-bar">
        <span className="pname">{p.first_name} {p.last_name}</span>
        <span className="pmeta">DOB {p.dob}</span>
        {encounter.is_returning && <span className="returning">Returning patient</span>}
      </div>

      <main className="workspace">
        {/* Left column: transcript */}
        <section className="panel">
          <div className="panel-head">
            <h3>Transcript / Clinical Notes</h3>
          </div>
          <textarea className="transcript" rows={18}
            placeholder="Paste the visit transcript or type clinical observations…"
            value={transcript} onChange={(e) => setTranscript(e.target.value)} />
          <div className="row-between">
            <button className="primary" disabled={generating || !transcript.trim()} onClick={generate}>
              {generating ? "Generating…" : "Generate Note"}
            </button>
            {draftSaved && <span className="muted">Draft saved {draftSaved}</span>}
          </div>
        </section>

        {/* Middle column: SOAP + ICD */}
        <section className="panel">
          <div className="panel-head">
            <h3>SOAP Note</h3>
            <button className="primary" disabled={!canSave} onClick={save}
              title={canSave ? "" : "Add clinical content before saving"}>
              {saving ? "Saving…" : "Save Note"}
            </button>
          </div>

          {savedOk && (
            <div className="notice success">
              <span className="ico">✓</span>
              <span>Clinical note saved to the patient record.</span>
            </div>
          )}

          {toolNotice && (
            <div className="notice info">
              <span className="ico">i</span>
              <span>{toolNotice}</span>
            </div>
          )}

          {soap.insufficient ? (
            <div className="notice warning">
              <span className="ico">!</span>
              <span>This transcript does not contain enough clinical information to generate a note. Please add clinical detail and generate again.</span>
            </div>
          ) : (
            <div className="soap">
              <SoapBox label="S — Subjective" value={soap.subjective}
                onChange={(v) => setSoap({ ...soap, subjective: v })} />
              <SoapBox label="O — Objective" value={soap.objective}
                onChange={(v) => setSoap({ ...soap, objective: v })} />
              <SoapBox label="A — Assessment (with ICD-10)" value={soap.assessment}
                onChange={(v) => setSoap({ ...soap, assessment: v })} />
              <SoapBox label="P — Plan" value={soap.plan}
                onChange={(v) => setSoap({ ...soap, plan: v })} />
            </div>
          )}

          {/* ICD-10 search */}
          <div className="icd">
            <label>ICD-10 search (enter a symptom or diagnosis)</label>
            <input placeholder="e.g. shortness of breath on exertion"
              value={icdQuery} onChange={(e) => setIcdQuery(e.target.value)} />
            {icdHits.length > 0 && (
              <ul className="icd-hits">
                {icdHits.map((h) => (
                  <li key={h.code} onClick={() => appendIcd(h)} title="Click to add to Assessment">
                    <code>{h.code}</code>
                    <span className="desc">{h.description}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Right column: version history */}
        <aside className="panel narrow">
          <div className="panel-head">
            <h3>Version History</h3>
            {versions.length >= 2 && (
              <button className="ghost" onClick={() => nav(`/diff?id=${encounter.id}`)}>Compare</button>
            )}
          </div>
          {versions.length === 0 && <p className="muted">No saved versions yet.</p>}
          <ul className="versions">
            {versions.map((v) => (
              <li key={v.version_no} onClick={() => viewVersion(v)}>
                <strong>Version {v.version_no}</strong>
                <span className="vmeta">{v.author_name}</span>
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
      <img className="brand-logo" src="/mednotecopilot.png" alt="MedNote Copilot" onClick={() => nav("/")} />
      <button className="ghost" onClick={() => nav("/")}>Dashboard</button>
      <span className="user">
        {user?.first_name} {user?.last_name}
        <span className="role">{user?.role}</span>
      </span>
      <button className="ghost" onClick={logout}>Sign out</button>
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
