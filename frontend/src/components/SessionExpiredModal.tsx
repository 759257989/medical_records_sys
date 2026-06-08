// frontend/src/components/SessionExpiredModal.tsx
import { useState } from "react";
import { useAuth } from "../auth/AuthContext";

export default function SessionExpiredModal() {
  const { user, sessionExpired, login } = useAuth();
  const [email, setEmail] = useState(user?.email ?? "");   // prefill email; provider only needs the password
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Only show when a logged-in user's session lapses mid-work (to preserve their unsaved content).
  // If there is no user (e.g. an invalid token on first load), ProtectedRoute handles the redirect.
  if (!sessionExpired || !user) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      // On success, AuthContext sets sessionExpired=false → this modal unmounts itself,
      // while the workspace was never unmounted, so the SOAP draft is preserved intact.
      await login(email, password);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 403 || detail === "account_inactive") {
        // EDGE-3: account deactivated by an admin
        setError("This account has been deactivated. Please contact your administrator. Your work is still saved locally and has not been lost.");
      } else {
        setError("Email or password is incorrect. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>Session expired</h2>
        <p className="muted">
          Your session has ended for security. <strong>Your work has not been lost</strong> —
          sign in again to continue saving.
        </p>
        <form onSubmit={submit}>
          <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input placeholder="Password" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in & continue"}
          </button>
        </form>
      </div>
    </div>
  );
}
