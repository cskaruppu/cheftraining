import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  Cell,
  LabelList,
} from "recharts";
import { ModelInfo, SERIES, api, fmtCompact } from "../lib/api";
import { PageHeader, Spinner, tooltipStyle } from "../components/ui";

const blended = (m: ModelInfo) => (3 * m.input_price + m.output_price) / 4;
const avgQ = (m: ModelInfo) =>
  Object.values(m.quality).reduce((a, b) => a + b, 0) / 7;

export default function Compare() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [sel, setSel] = useState<string[]>(["claude-sonnet-4.5", "gpt-5-mini", "llama-4-maverick"]);
  const [radar, setRadar] = useState<Record<string, number | string>[]>([]);
  const [selModels, setSelModels] = useState<ModelInfo[]>([]);

  useEffect(() => {
    api.models().then((d) => setModels(d.models));
  }, []);

  useEffect(() => {
    if (sel.length === 0) {
      setRadar([]);
      setSelModels([]);
      return;
    }
    api.compare(sel).then((d) => {
      setRadar(d.radar);
      setSelModels(d.models);
    });
  }, [sel]);

  const toggle = (id: string) =>
    setSel((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : s.length >= 3 ? s : [...s, id],
    );

  const scatterData = useMemo(
    () =>
      models.map((m) => ({
        id: m.id,
        name: m.name,
        price: Number(blended(m).toFixed(2)),
        quality: Number(avgQ(m).toFixed(1)),
        selected: sel.includes(m.id),
      })),
    [models, sel],
  );

  if (!models.length) return <Spinner />;

  const specRows: { label: string; get: (m: ModelInfo) => string }[] = [
    { label: "Provider", get: (m) => m.provider },
    { label: "Source", get: (m) => (m.source === "open" ? "Open weights" : "Proprietary") },
    { label: "Context window", get: (m) => fmtCompact(m.context_window) },
    { label: "Input $/1M", get: (m) => `$${m.input_price.toFixed(2)}` },
    { label: "Output $/1M", get: (m) => `$${m.output_price.toFixed(2)}` },
    { label: "Blended $/1M", get: (m) => `$${blended(m).toFixed(2)}` },
    { label: "First token", get: (m) => `${m.latency_ms} ms` },
    { label: "Throughput", get: (m) => `${m.throughput_tps} tok/s` },
    { label: "Capabilities", get: (m) => m.capabilities.map((c) => c.replace("_", " ")).join(", ") },
    { label: "Self-hostable", get: (m) => (m.self_hostable ? "Yes" : "No") },
    { label: "Knowledge cutoff", get: (m) => m.knowledge_cutoff },
  ];

  return (
    <div>
      <PageHeader
        title="Compare Models"
        sub="Pick up to three models for a head-to-head across quality, price and specs"
      />

      <div className="flex flex-wrap gap-2 mb-6">
        {models.map((m) => {
          const idx = sel.indexOf(m.id);
          return (
            <button
              key={m.id}
              onClick={() => toggle(m.id)}
              className={`chip !py-1 !px-3 !text-xs transition ${
                idx >= 0 ? "!text-ink" : "hover:!text-ink"
              }`}
              style={idx >= 0 ? { borderColor: SERIES[idx], color: "#fff" } : {}}
            >
              {idx >= 0 && (
                <span
                  className="mr-1.5 inline-block h-2 w-2 rounded-full"
                  style={{ background: SERIES[idx] }}
                />
              )}
              {m.name}
            </button>
          );
        })}
      </div>

      {sel.length === 0 ? (
        <div className="card text-sm text-muted">Select at least one model above.</div>
      ) : (
        <>
          <div className="grid lg:grid-cols-2 gap-4 mb-4">
            <div className="card">
              <h2 className="text-sm font-medium mb-2">Quality by task dimension</h2>
              <ResponsiveContainer width="100%" height={300}>
                <RadarChart data={radar} outerRadius="72%">
                  <PolarGrid stroke="#2c2c2a" />
                  <PolarAngleAxis dataKey="dimension" tick={{ fill: "#c3c2b7", fontSize: 11 }} />
                  <PolarRadiusAxis domain={[60, 100]} tick={{ fill: "#898781", fontSize: 10 }} stroke="#383835" />
                  {selModels.map((m, i) => (
                    <Radar
                      key={m.id}
                      name={m.name}
                      dataKey={m.id}
                      stroke={SERIES[i]}
                      fill={SERIES[i]}
                      fillOpacity={0.12}
                      strokeWidth={2}
                    />
                  ))}
                  <Legend wrapperStyle={{ fontSize: 12, color: "#c3c2b7" }} />
                  <Tooltip contentStyle={tooltipStyle} />
                </RadarChart>
              </ResponsiveContainer>
            </div>

            <div className="card">
              <h2 className="text-sm font-medium mb-2">
                Price vs quality — selected models highlighted
              </h2>
              <ResponsiveContainer width="100%" height={300}>
                <ScatterChart margin={{ top: 10, right: 20, left: -8, bottom: 4 }}>
                  <CartesianGrid stroke="#2c2c2a" />
                  <XAxis
                    type="number"
                    dataKey="price"
                    name="Blended $/1M"
                    stroke="#898781"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: "#383835" }}
                    scale="log"
                    domain={[0.05, 12]}
                    ticks={[0.1, 0.5, 1, 2, 5, 10]}
                    label={{ value: "blended $/1M tokens (log)", position: "insideBottom", offset: -2, fill: "#898781", fontSize: 10 }}
                  />
                  <YAxis
                    type="number"
                    dataKey="quality"
                    name="Avg quality"
                    domain={[72, 96]}
                    stroke="#898781"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    cursor={{ strokeDasharray: "3 3", stroke: "#898781" }}
                    formatter={(v: number, n: string) => [v, n]}
                    labelFormatter={() => ""}
                  />
                  <Scatter data={scatterData} isAnimationActive={false}>
                    {scatterData.map((d) => (
                      <Cell
                        key={d.id}
                        fill={d.selected ? SERIES[sel.indexOf(d.id)] : "#52514e"}
                        r={d.selected ? 7 : 4}
                        stroke={d.selected ? "#1a1a19" : "none"}
                        strokeWidth={2}
                      />
                    ))}
                    <LabelList
                      dataKey="name"
                      position="top"
                      content={(props: any) => {
                        const d = scatterData[props.index];
                        if (!d?.selected) return null;
                        // alternate above/below so nearby labels don't collide
                        const below = sel.indexOf(d.id) % 2 === 1;
                        return (
                          <text x={props.x} y={below ? props.y + 20 : props.y - 12} fill="#c3c2b7" fontSize={11} textAnchor="middle">
                            {d.name}
                          </text>
                        );
                      }}
                    />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-edge">
                  <th className="py-2 pr-4 text-xs text-muted font-normal">Spec</th>
                  {selModels.map((m, i) => (
                    <th key={m.id} className="py-2 pr-4 font-medium">
                      <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: SERIES[i] }} />
                      {m.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {specRows.map((row) => (
                  <tr key={row.label} className="border-b border-edge/50">
                    <td className="py-2 pr-4 text-xs text-muted">{row.label}</td>
                    {selModels.map((m) => (
                      <td key={m.id} className="py-2 pr-4 text-ink2 tabular-nums">
                        {row.get(m)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
