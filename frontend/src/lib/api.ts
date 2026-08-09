export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  source: "open" | "closed";
  context_window: number;
  max_output: number;
  input_price: number;
  output_price: number;
  latency_ms: number;
  throughput_tps: number;
  quality: Record<string, number>;
  capabilities: string[];
  license: string;
  regions: string[];
  knowledge_cutoff: string;
  self_hostable: boolean;
  params_b: number | null;
  size_class: "slm" | "mid" | "large";
}

export interface RecommendResult {
  model: ModelInfo;
  score: number;
  breakdown: { quality: number; cost: number; speed: number };
  blended_price: number;
  reasons: string[];
}

export interface RecommendResponse {
  results: RecommendResult[];
  excluded: { id: string; name: string; reason: string }[];
  chosen_vs_suggested?: {
    chosen: ModelInfo;
    suggested: ModelInfo;
    deltas: string[];
    same: boolean;
  };
  message?: string;
}

export interface AnalyticsSummary {
  kpis: {
    requests_24h: number;
    requests_total: number;
    spend_total: number;
    avg_latency_ms: number;
    cache_hit_rate: number;
  };
  daily: { day: string; requests: number; cost: number }[];
  by_model: { model: string; requests: number; cost: number; tokens: number }[];
  recent: {
    ts: string;
    model_name: string;
    tokens_in: number;
    tokens_out: number;
    latency_ms: number;
    cached: boolean;
    cost: number;
  }[];
}

export interface RoutingReceipt {
  model_id: string;
  reason: string;
  dimension: string;
  cost_usd: number;
  cheapest_comparable?: {
    model_id: string;
    model_name: string;
    cost_usd: number;
    savings_pct: number;
    quality_delta: number;
  };
}

export interface PlaygroundResult {
  model_id: string;
  model_name: string;
  provider: string;
  text: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  cost: number;
  receipt?: RoutingReceipt;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  models: () =>
    req<{ models: ModelInfo[]; providers: string[]; quality_dims: string[] }>(
      "/api/models",
    ),
  useCases: () =>
    req<{ use_cases: { id: string; label: string }[] }>("/api/use-cases"),
  recommend: (body: unknown) =>
    req<RecommendResponse>("/api/recommend", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  compare: (model_ids: string[]) =>
    req<{ models: ModelInfo[]; radar: Record<string, number | string>[] }>(
      "/api/compare",
      { method: "POST", body: JSON.stringify({ model_ids }) },
    ),
  playground: (model_ids: string[], prompt: string) =>
    req<{ results: PlaygroundResult[] }>("/api/playground", {
      method: "POST",
      body: JSON.stringify({ model_ids, prompt }),
    }),
  analytics: () => req<AnalyticsSummary>("/api/analytics/summary"),
};

export const SERIES = ["#3987e5", "#d95926", "#199e70"];

export const fmtMoney = (v: number) =>
  v >= 100 ? `$${v.toFixed(0)}` : v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(4)}`;

export const fmtCompact = (v: number) =>
  Intl.NumberFormat("en", { notation: "compact" }).format(v);
