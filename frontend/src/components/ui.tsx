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

export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="text-2xl font-semibold mt-2">{value}</div>
      {hint && <div className="text-xs text-ink2 mt-1">{hint}</div>}
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
