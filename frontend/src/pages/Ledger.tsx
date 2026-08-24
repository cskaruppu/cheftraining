import { useEffect, useState } from "react";
import { PageHeader, Spinner } from "../components/ui";

interface Entry {
  id: number;
  ts: string;
  kind: string;
  policy: string | null;
  model_id: string;
  team_id: string | null;
  summary: string;
  receipt: Record<string, unknown>;
}

interface LedgerData {
  total: number;
  window_days: number;
  entries: Entry[];
}

const KIND_CHIP: Record<string, string> = {
  routing: "border-s1/50 text-s1",
  enforcement: "border-warn/50 text-warn",
  failover: "border-crit/50 text-crit",
  placement: "border-s3/50 text-s3",
};

const KINDS = ["", "routing", "enforcement", "failover", "placement"];
const RANGES = [7, 14, 30];

export default function Ledger() {
  const [data, setData] = useState<LedgerData | null>(null);
  const [kind, setKind] = useState("");
  const [days, setDays] = useState(14);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    setData(null);
    const q = new URLSearchParams({ days: String(days) });
    if (kind) q.set("kind", kind);
    fetch(`/api/ledger?${q}`).then((r) => r.json()).then(setData);
  }, [kind, days]);

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="Decision Ledger"
          sub="Every model decision the platform makes — routing, enforcement, failover, placement — recorded with its full receipt. Gateways log requests; Modelect logs justifications. Prompt contents are never stored."
        />
        <a href={`/api/ledger/export?days=${days}`}
          className="btn !text-xs shrink-0 mt-1"
          title="CSV export for auditors — AI-governance record-keeping">
          Export CSV
        </a>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex rounded-lg border border-edge overflow-hidden">
          {RANGES.map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={`px-2.5 py-1 text-[11px] transition-colors ${
                d === days ? "bg-raised text-ink" : "text-muted hover:text-ink2"}`}>
              {d}d
            </button>
          ))}
        </div>
        <div className="flex rounded-lg border border-edge overflow-hidden">
          {KINDS.map((k) => (
            <button key={k} onClick={() => setKind(k)}
              className={`px-2.5 py-1 text-[11px] transition-colors ${
                k === kind ? "bg-raised text-ink" : "text-muted hover:text-ink2"}`}>
              {k || "all"}
            </button>
          ))}
        </div>
        {data && (
          <span className="chip !text-[10px]">
            {data.total} decisions · {days}d{data.total > data.entries.length
              ? ` · newest ${data.entries.length} shown` : ""}
          </span>
        )}
      </div>

      {!data ? <Spinner /> : data.entries.length === 0 ? (
        <div className="card text-sm text-muted">
          No decisions recorded in this window — send traffic through the gateway
          and every routing choice will appear here with its receipt.
        </div>
      ) : (
        <div className="card">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-edge">
                  <th className="py-2 pr-4 font-normal">Time (UTC)</th>
                  <th className="py-2 pr-4 font-normal">Kind</th>
                  <th className="py-2 pr-4 font-normal">Policy</th>
                  <th className="py-2 pr-4 font-normal">Decision</th>
                  <th className="py-2 pr-4 font-normal">Team</th>
                  <th className="py-2 font-normal"></th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((e) => (
                  <>
                    <tr key={e.id} className="border-b border-edge/50 text-ink2">
                      <td className="py-2 pr-4 tabular-nums whitespace-nowrap">
                        {e.ts.slice(5, 19).replace("T", " ")}
                      </td>
                      <td className="py-2 pr-4">
                        <span className={`chip !py-0 !text-[10px] ${KIND_CHIP[e.kind] ?? ""}`}>
                          {e.kind}
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-xs">{e.policy ?? "—"}</td>
                      <td className="py-2 pr-4 text-ink max-w-[480px]">
                        <span className="block truncate" title={e.summary}>{e.summary}</span>
                      </td>
                      <td className="py-2 pr-4 text-xs">{e.team_id ?? "—"}</td>
                      <td className="py-2">
                        <button className="chip !text-[10px] hover:!text-ink transition"
                          onClick={() => setOpen(open === e.id ? null : e.id)}>
                          {open === e.id ? "hide receipt" : "receipt"}
                        </button>
                      </td>
                    </tr>
                    {open === e.id && (
                      <tr key={`${e.id}-r`} className="border-b border-edge/50">
                        <td colSpan={6} className="py-2">
                          <pre className="bg-page border border-edge rounded-lg px-3 py-2.5 text-[11px] leading-relaxed text-ink2 overflow-x-auto font-mono max-h-72">
                            {JSON.stringify(e.receipt, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-muted mt-3">
            Append-only record. Export covers the selected window (up to 500 newest
            entries) — the raw table persists in the platform database for full audits.
          </p>
        </div>
      )}
    </div>
  );
}
