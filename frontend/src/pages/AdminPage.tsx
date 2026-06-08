// frontend/src/pages/AdminPage.tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import { useAuth } from "../auth/AuthContext";

type Provider = { id: string; email: string; first_name: string; last_name: string; role: string; is_active: boolean; created_at: string };
type EncRow = { id: string; status: string; created_at: string; patient_name: string; dob: string; provider_name: string };
type Template = { id: string; name: string; encounter_type: string | null; system_prompt: string; is_active: boolean; created_at: string; updated_at: string };
type Tab = "encounters" | "providers" | "templates";

const STATUS_LABEL: Record<string, string> = { draft: "Draft", generated: "Generated", finalized: "Finalized" };

export default function AdminPage() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [tab, setTab] = useState<Tab>("encounters");

  return (
    <div className="page">
      <header className="topbar">
        <img className="brand-logo" src="/mednotecopilot.png" alt="MedNote Copilot" onClick={() => nav("/admin")} />
        <span className="user">
          {user?.first_name} {user?.last_name}
          <span className="role">{user?.role}</span>
        </span>
        <button className="ghost" onClick={logout}>Sign out</button>
      </header>
      <nav className="tabs">
        <button className={tab === "encounters" ? "active" : ""} onClick={() => setTab("encounters")}>All Encounters</button>
        <button className={tab === "providers" ? "active" : ""} onClick={() => setTab("providers")}>Providers</button>
        <button className={tab === "templates" ? "active" : ""} onClick={() => setTab("templates")}>Note Templates</button>
      </nav>
      <main className="content">
        {tab === "encounters" && <EncountersTab />}
        {tab === "providers" && <ProvidersTab />}
        {tab === "templates" && <TemplatesTab />}
      </main>
    </div>
  );
}

// ── All encounters ─────────────────────────────────────────────────────────────
function EncountersTab() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [rows, setRows] = useState<EncRow[]>([]);
  const [providerId, setProviderId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  useEffect(() => { api.get<Provider[]>("/admin/providers").then((r) => setProviders(r.data)).catch(() => {}); }, []);

  const load = () => {
    const params: Record<string, string> = {};
    if (providerId) params.provider_id = providerId;
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    api.get<EncRow[]>("/admin/encounters", { params }).then((r) => setRows(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);   // initial load: all

  return (
    <div>
      <div className="filters">
        <label>Provider</label>
        <select value={providerId} onChange={(e) => setProviderId(e.target.value)}>
          <option value="">All providers</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}
        </select>
        <label>From</label>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <label>To</label>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        <button className="primary" onClick={load}>Search</button>
      </div>
      <table className="grid">
        <thead><tr><th>Date</th><th>Provider</th><th>Patient</th><th>DOB</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id}>
              <td>{new Date(e.created_at).toLocaleString()}</td>
              <td>{e.provider_name}</td>
              <td>{e.patient_name}</td>
              <td>{e.dob}</td>
              <td><span className={`badge ${e.status}`}>{STATUS_LABEL[e.status] ?? e.status}</span></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={5} className="muted">No results.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

// ── Providers ──────────────────────────────────────────────────────────────────
function ProvidersTab() {
  const [list, setList] = useState<Provider[]>([]);
  const blank = { email: "", password: "", first_name: "", last_name: "" };
  const [form, setForm] = useState(blank);
  const [msg, setMsg] = useState("");

  const load = () => api.get<Provider[]>("/admin/providers").then((r) => setList(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg("");
    try {
      await api.post("/admin/providers", form);
      setForm(blank); setMsg("Provider created."); load();
    } catch {
      setMsg("Could not create provider (email may already exist).");
    }
  };

  const toggle = async (p: Provider) => {
    await api.patch(`/admin/providers/${p.id}/active`, { is_active: !p.is_active });
    load();
  };

  return (
    <div className="two-col">
      <div>
        <h3>Provider Accounts</h3>
        <table className="grid">
          <thead><tr><th>Name</th><th>Email</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id} className={p.is_active ? "" : "row-off"}>
                <td>{p.first_name} {p.last_name}</td>
                <td>{p.email}</td>
                <td>{p.is_active ? <span className="badge ok">Active</span> : <span className="badge off">Deactivated</span>}</td>
                <td className="actions"><button className="ghost" onClick={() => toggle(p)}>{p.is_active ? "Deactivate" : "Activate"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>Add Provider</h3>
        <form className="card" onSubmit={create}>
          <input required placeholder="First name" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <input required placeholder="Last name" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          <input required type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input required type="text" placeholder="Initial password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <button className="primary" type="submit">Create Account</button>
          {msg && <p className="muted">{msg}</p>}
        </form>
      </div>
    </div>
  );
}

// ── Note templates ─────────────────────────────────────────────────────────────
function TemplatesTab() {
  const [list, setList] = useState<Template[]>([]);
  const blank = { name: "", encounter_type: "", system_prompt: "", is_active: true };
  const [form, setForm] = useState(blank);
  const [editingId, setEditingId] = useState<string | null>(null);

  const load = () => api.get<Template[]>("/admin/templates").then((r) => setList(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const startNew = () => { setEditingId(null); setForm(blank); };
  const startEdit = (t: Template) => {
    setEditingId(t.id);
    setForm({ name: t.name, encounter_type: t.encounter_type || "", system_prompt: t.system_prompt, is_active: t.is_active });
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (editingId) await api.put(`/admin/templates/${editingId}`, form);
    else await api.post("/admin/templates", form);
    startNew(); load();
  };

  const remove = async (t: Template) => {
    if (!window.confirm(`Delete template "${t.name}"?`)) return;
    await api.delete(`/admin/templates/${t.id}`);
    if (editingId === t.id) startNew();
    load();
  };

  return (
    <div className="two-col">
      <div>
        <h3>Templates</h3>
        <table className="grid">
          <thead><tr><th>Name</th><th>Type</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {list.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td className="muted">{t.encounter_type || "—"}</td>
                <td>{t.is_active ? <span className="badge ok">Active</span> : <span className="badge off">Inactive</span>}</td>
                <td className="actions">
                  <button className="ghost" onClick={() => startEdit(t)}>Edit</button>
                  <button className="ghost" onClick={() => remove(t)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>{editingId ? "Edit Template" : "New Template"}</h3>
        <form className="card" onSubmit={submit}>
          <input required placeholder="Template name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="Encounter type (optional, e.g. ortho_followup)" value={form.encounter_type} onChange={(e) => setForm({ ...form, encounter_type: e.target.value })} />
          <textarea required rows={8} placeholder="System prompt (controls the AI's documentation style)"
            value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />
          <label className="check">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
            Active (selectable by providers)
          </label>
          <div className="row">
            <button className="primary" type="submit">{editingId ? "Save Changes" : "Create Template"}</button>
            {editingId && <button className="ghost" type="button" onClick={startNew}>Cancel</button>}
          </div>
        </form>
      </div>
    </div>
  );
}
