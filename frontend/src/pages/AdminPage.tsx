// frontend/src/pages/AdminPage.tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import { useAuth } from "../auth/AuthContext";

type Provider = { id: string; email: string; first_name: string; last_name: string; role: string; is_active: boolean; created_at: string };
type EncRow = { id: string; status: string; created_at: string; patient_name: string; dob: string; provider_name: string };
type Template = { id: string; name: string; encounter_type: string | null; system_prompt: string; is_active: boolean; created_at: string; updated_at: string };
type Tab = "encounters" | "providers" | "templates";

export default function AdminPage() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [tab, setTab] = useState<Tab>("encounters");

  return (
    <div className="page">
      <header className="topbar">
        <strong style={{ cursor: "pointer" }} onClick={() => nav("/")}>Clinical Scribe · Admin</strong>
        <span>{user?.first_name} {user?.last_name} · {user?.role}</span>
        <button onClick={logout}>退出</button>
      </header>
      <nav className="tabs">
        <button className={tab === "encounters" ? "active" : ""} onClick={() => setTab("encounters")}>全部就诊</button>
        <button className={tab === "providers" ? "active" : ""} onClick={() => setTab("providers")}>医生账号</button>
        <button className={tab === "templates" ? "active" : ""} onClick={() => setTab("templates")}>笔记模板</button>
      </nav>
      <main className="content">
        {tab === "encounters" && <EncountersTab />}
        {tab === "providers" && <ProvidersTab />}
        {tab === "templates" && <TemplatesTab />}
      </main>
    </div>
  );
}

// ── 全部就诊 ──────────────────────────────────────────────────────────────────
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
  useEffect(() => { load(); }, []);   // 首次加载全部

  return (
    <div>
      <div className="filters">
        <select value={providerId} onChange={(e) => setProviderId(e.target.value)}>
          <option value="">全部医生</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}
        </select>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <span>至</span>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        <button className="primary" onClick={load}>查询</button>
      </div>
      <table className="grid">
        <thead><tr><th>就诊时间</th><th>医生</th><th>患者</th><th>DOB</th><th>状态</th></tr></thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id}>
              <td>{new Date(e.created_at).toLocaleString()}</td>
              <td>{e.provider_name}</td>
              <td>{e.patient_name}</td>
              <td>{e.dob}</td>
              <td><span className="badge">{e.status}</span></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={5} className="muted">无结果</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

// ── 医生账号 ──────────────────────────────────────────────────────────────────
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
      setForm(blank); setMsg("已创建"); load();
    } catch {
      setMsg("创建失败（邮箱可能已存在）");
    }
  };

  const toggle = async (p: Provider) => {
    await api.patch(`/admin/providers/${p.id}/active`, { is_active: !p.is_active });
    load();
  };

  return (
    <div className="two-col">
      <div>
        <h3>医生列表</h3>
        <table className="grid">
          <thead><tr><th>姓名</th><th>邮箱</th><th>状态</th><th></th></tr></thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id} className={p.is_active ? "" : "row-off"}>
                <td>{p.first_name} {p.last_name}</td>
                <td>{p.email}</td>
                <td>{p.is_active ? <span className="badge ok">在用</span> : <span className="badge off">已停用</span>}</td>
                <td><button onClick={() => toggle(p)}>{p.is_active ? "停用" : "启用"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>新增医生</h3>
        <form className="card" onSubmit={create}>
          <input required placeholder="名" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <input required placeholder="姓" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          <input required type="email" placeholder="邮箱" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input required type="text" placeholder="初始密码" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <button className="primary" type="submit">创建账号</button>
          {msg && <p className="muted">{msg}</p>}
        </form>
      </div>
    </div>
  );
}

// ── 笔记模板 ──────────────────────────────────────────────────────────────────
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
    if (!window.confirm(`删除模板「${t.name}」？`)) return;
    await api.delete(`/admin/templates/${t.id}`);
    if (editingId === t.id) startNew();
    load();
  };

  return (
    <div className="two-col">
      <div>
        <h3>模板列表</h3>
        <table className="grid">
          <thead><tr><th>名称</th><th>类型</th><th>状态</th><th></th></tr></thead>
          <tbody>
            {list.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td className="muted">{t.encounter_type || "—"}</td>
                <td>{t.is_active ? <span className="badge ok">启用</span> : <span className="badge off">停用</span>}</td>
                <td>
                  <button onClick={() => startEdit(t)}>编辑</button>
                  <button onClick={() => remove(t)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>{editingId ? "编辑模板" : "新建模板"}</h3>
        <form className="card" onSubmit={submit}>
          <input required placeholder="模板名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="就诊类型（可选，如 ortho_followup）" value={form.encounter_type} onChange={(e) => setForm({ ...form, encounter_type: e.target.value })} />
          <textarea required rows={8} placeholder="System prompt（决定 AI 生成风格）"
            value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />
          <label className="check">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
            启用（provider 可选用）
          </label>
          <div className="row">
            <button className="primary" type="submit">{editingId ? "保存修改" : "创建模板"}</button>
            {editingId && <button type="button" onClick={startNew}>取消</button>}
          </div>
        </form>
      </div>
    </div>
  );
}