import { ReactNode } from "react";
import { ModelInfo } from "../lib/api";

export function PageHeader({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="text-sm text-muted mt-1">{sub}</p>
    </div>
  );
}

export function Sparkline({ values, color = "#3987e5" }: { values: number[]; color?: string }) {
  if (values.length < 2) return null;
  const w = 96, h = 26, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${pad + (i / (values.length - 1)) * (w - pad * 2)},${h - pad - ((v - min) / span) * (h - pad * 2)}`)
    .join(" ");
  return (
    <svg width={w} height={h} className="block" aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5"
        strokeLinejoin="round" strokeLinecap="round" opacity="0.8" />
    </svg>
  );
}

export function StatTile({
  label,
  value,
  hint,
  delta,
  goodWhenDown,
  spark,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  /** period-over-period % change; null/undefined hides the badge */
  delta?: number | null;
  /** for latency-like metrics a falling delta is the good direction */
  goodWhenDown?: boolean;
  spark?: number[];
}) {
  const up = (delta ?? 0) > 0;
  const good = delta === 0 ? true : goodWhenDown ? !up : up;
  return (
    <div className="card">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
        {delta !== null && delta !== undefined && (
          <span className={`text-[10px] tabular-nums ${good ? "text-good" : "text-warn"}`}
            title="vs the previous period of the same length">
            {up ? "▲" : delta < 0 ? "▼" : "—"} {Math.abs(delta).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="text-2xl font-semibold mt-2">{value}</div>
      <div className="flex items-end justify-between gap-2 mt-1">
        {hint ? <div className="text-xs text-ink2">{hint}</div> : <span />}
        {spark && <Sparkline values={spark} />}
      </div>
    </div>
  );
}

export function ScoreBar({
  value,
  color = "#3987e5",
  label,
}: {
  value: number;
  color?: string;
  label?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      {label && <span className="text-xs text-muted w-14 shrink-0">{label}</span>}
      <div className="h-1.5 flex-1 rounded-full bg-grid overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.min(100, value)}%`, background: color }}
        />
      </div>
      <span className="text-xs text-ink2 w-9 text-right tabular-nums">
        {value.toFixed(0)}
      </span>
    </div>
  );
}

export function SourceBadge({ model }: { model: ModelInfo }) {
  return model.source === "open" ? (
    <span className="chip border-s3/40 text-s3">open weights</span>
  ) : (
    <span className="chip">proprietary</span>
  );
}

export function Spinner() {
  return (
    <div className="flex justify-center py-10">
      <div className="h-6 w-6 rounded-full border-2 border-grid border-t-s1 animate-spin" />
    </div>
  );
}

export const tooltipStyle = {
  backgroundColor: "#222221",
  border: "1px solid rgba(255,255,255,0.10)",
  borderRadius: 8,
  color: "#ffffff",
  fontSize: 12,
};
