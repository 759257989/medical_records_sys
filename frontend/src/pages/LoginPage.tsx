// frontend/src/pages/LoginPage.tsx
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const peekTimer = useRef<number | null>(null);

  // Reveal the password briefly, then auto-hide for safety.
  const peekPassword = () => {
    if (peekTimer.current) clearTimeout(peekTimer.current);
    setShowPw(true);
    peekTimer.current = window.setTimeout(() => setShowPw(false), 1500);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      const u = await login(email, password);
      nav(u.role === "admin" ? "/admin" : "/");   // admins go straight to the console
    } catch (err: any) {
      if (err?.response?.status === 403) setError("This account has been deactivated. Please contact your administrator.");
      else setError("Email or password is incorrect.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-split">
      {/* Branded panel */}
      <aside className="login-aside">
        <div className="logo-chip">
          <img src="/mednotecopilot.png" alt="MedNote Copilot" />
        </div>
        <h1>Clinical documentation,<br />accelerated.</h1>
        <p className="lede">
          Transform patient encounter transcripts and provider observations into structured SOAP notes with AI-assisted documentation support.
        </p>
        <ul className="features">
          <li><span className="tick">✓</span><span>Convert visit transcripts into organized SOAP notes.</span></li>
          <li><span className="tick">✓</span><span>Built-in ICD-10 coding and prior-history awareness.</span></li>
          <li><span className="tick">✓</span><span>Full version history and audit trail for every encounter.</span></li>
        </ul>
      </aside>

      {/* Sign-in form */}
      <main className="login-main">
        <div className="login-card">
          <img className="form-logo" src="/mednotecopilot.png" alt="MedNote Copilot" />
          <h2>Sign in</h2>
          <p className="sub">Welcome back. Please sign in to continue.</p>
          <form onSubmit={submit}>
            <label className="field">Email</label>
            <input placeholder="you@clinic.example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
            <label className="field">Password</label>
            <div className="pw-wrap">
              <input
                placeholder="Password"
                type={showPw ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button type="button" className="pw-peek" onClick={peekPassword}
                title="Show password briefly" aria-label="Show password">
                {showPw ? <EyeOff /> : <Eye />}
              </button>
            </div>
            {error && <p className="error">{error}</p>}
            <button className="primary" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          </form>
        </div>
      </main>
    </div>
  );
}

function Eye() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function EyeOff() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}
