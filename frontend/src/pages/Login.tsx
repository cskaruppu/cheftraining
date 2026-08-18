import { useState } from "react";

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const r = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!r.ok) {
        setErr((await r.json()).detail ?? "login failed");
        return;
      }
      onLogin();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid place-items-center bg-page">
      <form onSubmit={submit} className="card w-[360px] !p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-s1 to-[#1c5cab] grid place-items-center text-white font-semibold shadow-lg shadow-s1/20">
            M
          </div>
          <div>
            <div className="text-[16px] font-semibold tracking-tight leading-none">Modelect</div>
            <div className="text-[10px] text-muted mt-1 tracking-wide uppercase">LLM Orchestrator</div>
          </div>
        </div>

        <label className="text-xs text-muted block mb-1.5">Username</label>
        <input className="input w-full mb-3" value={username} autoFocus
          onChange={(e) => setUsername(e.target.value)} />
        <label className="text-xs text-muted block mb-1.5">Password</label>
        <input className="input w-full mb-4" type="password" value={password}
          onChange={(e) => setPassword(e.target.value)} />

        {err && <div className="text-sm text-crit mb-3">{err}</div>}
        <button className="btn w-full" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="text-[11px] text-muted mt-5 leading-relaxed">
          Demo accounts — admin: <code className="text-ink2">admin</code> /{" "}
          <code className="text-ink2">modelect-admin</code> · team user:{" "}
          <code className="text-ink2">support-bot</code> /{" "}
          <code className="text-ink2">modelect-user</code>
          <br />
          Production replaces this with SSO (Keycloak / OIDC).
        </p>
      </form>
    </div>
  );
}
