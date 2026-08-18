import { useEffect, useState } from "react";
import { fmtCompact, fmtMoney } from "../lib/api";
import { PageHeader, Spinner } from "../components/ui";

interface TeamView {
  id: string;
  name: string;
  policy: string;
  budget_usd: number;
  api_key: string;
  enabled: boolean;
  rate_limit_tpm: number | null;
  allowed_tiers: string | null;
  max_input_tokens: number | null;
  tokens: number;
  top_model: string;
  spend: number;
  pct: number;
  state: string;
}

export default function MyUsage() {
  const [team, setTeam] = useState<TeamView | null>(null);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const refresh = () =>
      fetch("/api/me/team")
        .then((r) => (r.ok ? r.json() : r.json().then((e) => Promise.reject(e.detail))))
        .then(setTeam)
        .catch((e) => setErr(String(e)));
    refresh();
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, []);

  if (err) return <div className="card text-sm text-warn">{err}</div>;
  if (!team) return <Spinner />;

  const barColor = team.pct >= 90 ? "#d03b3b" : team.pct >= 70 ? "#fab219" : "#3987e5";

  return (
    <div>
      <PageHeader
        title="My Usage"
        sub={`Team ${team.name} — your budget, guardrails and API key`}
      />
      <div className="grid lg:grid-cols-2 gap-4 max-w-[900px]">
        <div className="card">
          <h2 className="text-sm font-medium mb-3">Budget · rolling 30 days</h2>
          <div className="flex items-baseline gap-2 mb-2">
            <span className="text-2xl font-semibold tabular-nums">{fmtMoney(team.spend)}</span>
            <span className="text-sm text-muted">of {fmtMoney(team.budget_usd)} ({team.pct.toFixed(0)}%)</span>
          </div>
          <div className="h-2 rounded-full bg-grid overflow-hidden mb-3">
            <div className="h-full rounded-full"
              style={{ width: `${Math.min(100, team.pct)}%`, background: barColor }} />
          </div>
          <div className="text-xs text-ink2">
            {fmtCompact(team.tokens)} tokens · top model: {team.top_model}
          </div>
          <div className="flex flex-wrap gap-1.5 mt-3">
            <span className="chip">policy: {team.policy}</span>
            {team.allowed_tiers && <span className="chip">tiers: {team.allowed_tiers}</span>}
            {team.rate_limit_tpm && <span className="chip">{(team.rate_limit_tpm / 1000).toFixed(0)}k tokens/min</span>}
            {team.max_input_tokens && <span className="chip">max input: {fmtCompact(team.max_input_tokens)}</span>}
            {!team.enabled && <span className="chip border-crit/50 text-crit">paused by admin</span>}
          </div>
          <p className="text-[11px] text-muted mt-3">
            At 100% of budget your requests are served by the smallest capable model
            (policy "{team.policy}") — your app keeps working.
          </p>
        </div>

        <div className="card">
          <h2 className="text-sm font-medium mb-3">Your API key</h2>
          <div className="flex items-center gap-2 mb-3">
            <code className="bg-raised rounded px-2.5 py-1.5 text-xs text-ink2">
              {team.api_key.slice(0, 10)}…{team.api_key.slice(-4)}
            </code>
            <button className="btn-ghost !py-1 !px-3 !text-xs"
              onClick={() => {
                navigator.clipboard?.writeText(team.api_key);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}>
              {copied ? "copied ✓" : "copy"}
            </button>
          </div>
          <p className="text-xs text-muted leading-relaxed">
            Use it as the <code className="text-ink2">Bearer</code> token against{" "}
            <code className="text-ink2">/v1/chat/completions</code>. The{" "}
            <span className="text-ink2">Integrate &amp; Verify</span> page generates
            ready-to-paste client code in your language — every call is attributed
            to your team and covered by the guardrails above.
          </p>
        </div>
      </div>
    </div>
  );
}
