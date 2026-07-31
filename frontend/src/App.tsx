import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Catalog from "./pages/Catalog";
import Recommend from "./pages/Recommend";
import Compare from "./pages/Compare";
import Playground from "./pages/Playground";
import Deploy from "./pages/Deploy";
import Evals from "./pages/Evals";
import Migrate from "./pages/Migrate";
import Integrate from "./pages/Integrate";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "▦" },
  { to: "/models", label: "Model Catalog", icon: "◈" },
  { to: "/recommend", label: "Recommend", icon: "✦" },
  { to: "/evals", label: "Evals", icon: "⚖" },
  { to: "/migrate", label: "Migrate", icon: "☁" },
  { to: "/deploy", label: "Deploy", icon: "⇪" },
  { to: "/integrate", label: "Integrate", icon: "‹›" },
  { to: "/compare", label: "Compare", icon: "⇄" },
  { to: "/playground", label: "Playground", icon: "▷" },
];

export default function App() {
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-edge bg-surface flex flex-col">
        <div className="px-5 py-5 border-b border-edge">
          <div className="text-lg font-semibold tracking-tight">
            Modelect<span className="text-s1">.</span>
          </div>
          <div className="text-[11px] text-muted mt-0.5">
            Multi-LLM Orchestrator
          </div>
        </div>
        <nav className="flex-1 py-3">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-5 py-2.5 text-sm transition ${
                  isActive
                    ? "text-ink bg-raised border-r-2 border-s1"
                    : "text-ink2 hover:text-ink"
                }`
              }
            >
              <span className="text-s1 w-4 text-center">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="px-5 py-4 border-t border-edge text-[11px] text-muted leading-relaxed">
          Demo build · seed data
          <br />
          Gateway: <code className="text-ink2">/v1/chat/completions</code>
        </div>
      </aside>
      <main className="flex-1 px-8 py-7 max-w-[1240px]">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/models" element={<Catalog />} />
          <Route path="/recommend" element={<Recommend />} />
          <Route path="/evals" element={<Evals />} />
          <Route path="/migrate" element={<Migrate />} />
          <Route path="/deploy" element={<Deploy />} />
          <Route path="/integrate" element={<Integrate />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/playground" element={<Playground />} />
        </Routes>
      </main>
    </div>
  );
}
