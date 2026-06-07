// frontend/src/components/SessionExpiredModal.tsx
import { useState } from "react";
import { useAuth } from "../auth/AuthContext";

export default function SessionExpiredModal() {
  const { user, sessionExpired, login } = useAuth();
  const [email, setEmail] = useState(user?.email ?? "");   // 预填邮箱，医生只需补密码
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // 只有【已登录用户】会话中途失效时才弹（目的：保住其内存里的未保存内容）。
  // 未登录场景（如首次加载 token 失效）user 为 null，交给 ProtectedRoute 跳登录页即可。
  if (!sessionExpired || !user) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      // 成功后 AuthContext 把 sessionExpired 置 false → 本弹窗 return null 自动消失，
      // 而 EncounterWorkspace 自始至终没被卸载，其 SOAP 草稿原样保留。
      await login(email, password);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 403 || detail === "account_inactive") {
        // EDGE-3：被管理员停用
        setError("此账号已被管理员停用，请联系管理员。你已录入的内容仍在本机，未丢失。");
      } else {
        setError("邮箱或密码不正确，请重试。");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>会话已过期</h2>
        <p className="muted">
          为保护数据安全，登录状态已失效。<strong>你正在编辑的内容没有丢失</strong>——
          重新登录后即可继续保存。
        </p>
        <form onSubmit={submit}>
          <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input placeholder="Password" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "登录中…" : "重新登录并继续"}
          </button>
        </form>
      </div>
    </div>
  );
}