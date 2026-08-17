import { ReactNode, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Catalog from "./pages/Catalog";
import Recommend from "./pages/Recommend";
import Compare from "./pages/Compare";
import Playground from "./pages/Playground";
import Deploy from "./pages/Deploy";
import Evals from "./pages/Evals";
import Migrate from "./pages/Migrate";
import Integrate from "./pages/Integrate";
import Clusters from "./pages/Clusters";
import Settings from "./pages/Settings";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
      {children}
    </svg>
  );
}

const ICONS: Record<string, ReactNode> = {
  dashboard: (
    <Icon>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </Icon>
  ),
  fleet: (
    <Icon>
      <rect x="2" y="4" width="20" height="6" rx="2" />
      <rect x="2" y="14" width="20" height="6" rx="2" />
      <path d="M6 7h.01M6 17h.01" />
    </Icon>
  ),
  catalog: (
    <Icon>
      <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" />
      <path d="m3.3 7 8.7 5 8.7-5" />
      <path d="M12 22V12" />
    </Icon>
  ),
  recommend: (
    <Icon>
      <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z" />
    </Icon>
  ),
  evals: (
    <Icon>
      <path d="m3 17 2 2 4-4" />
      <path d="m3 7 2 2 4-4" />
      <path d="M13 6h8M13 12h8M13 18h8" />
    </Icon>
  ),
  compare: (
    <Icon>
      <path d="m16 3 4 4-4 4" />
      <path d="M20 7H4" />
      <path d="m8 21-4-4 4-4" />
      <path d="M4 17h16" />
    </Icon>
  ),
  migrate: (
    <Icon>
      <path d="M4.4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.2" />
      <path d="M12 13v8" />
      <path d="m8 17 4 4 4-4" />
    </Icon>
  ),
  deploy: (
    <Icon>
      <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z" />
      <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z" />
      <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0" />
      <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
    </Icon>
  ),
  integrate: (
    <Icon>
      <path d="m16 18 6-6-6-6" />
      <path d="m8 6-6 6 6 6" />
    </Icon>
  ),
  playground: (
    <Icon>
      <polygon points="6 3 20 12 6 21 6 3" />
    </Icon>
  ),
  settings: (
    <Icon>
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </Icon>
  ),
};

const GROUPS: { label: string; items: { to: string; label: string; icon: string }[] }[] = [
  {
    label: "Overview",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
      { to: "/clusters", label: "GPU Fleet", icon: "fleet" },
    ],
  },
  {
    label: "Decide",
    items: [
      { to: "/models", label: "Model Catalog", icon: "catalog" },
      { to: "/recommend", label: "Recommend", icon: "recommend" },
      { to: "/evals", label: "Evals", icon: "evals" },
      { to: "/compare", label: "Compare", icon: "compare" },
    ],
  },
  {
    label: "Deploy",
    items: [
      { to: "/migrate", label: "Migrate from Cloud", icon: "migrate" },
      { to: "/deploy", label: "Deployments", icon: "deploy" },
    ],
  },
  {
    label: "Integrate",
    items: [
      { to: "/integrate", label: "Integrate & Verify", icon: "integrate" },
      { to: "/playground", label: "Playground", icon: "playground" },
    ],
  },
  {
    label: "Govern",
    items: [
      { to: "/settings", label: "Settings", icon: "settings" },
    ],
  },
];

const STORAGE_KEY = "modelect.nav.open";

function loadOpenState(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* first visit or blocked storage — fall through to default */
  }
  return Object.fromEntries(GROUPS.map((g) => [g.label, true]));
}

export default function App() {
  const location = useLocation();
  const [open, setOpen] = useState<Record<string, boolean>>(loadOpenState);

  // the group holding the current page always opens, so the active
  // item can never be hidden behind a collapsed section
  useEffect(() => {
    const active = GROUPS.find((g) => g.items.some((i) => i.to === location.pathname));
    if (active && !open[active.label]) {
      setOpen((o) => ({ ...o, [active.label]: true }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  const toggle = (label: string) =>
    setOpen((o) => {
      const next = { ...o, [label]: !o[label] };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* private mode — state just won't persist */
      }
      return next;
    });

  return (
    <div className="flex min-h-screen">
      <aside className="w-60 shrink-0 border-r border-edge bg-surface flex flex-col">
        <div className="flex items-center gap-3 px-5 py-5">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-s1 to-[#1c5cab] grid place-items-center text-white font-semibold text-sm shadow-lg shadow-s1/20">
            M
          </div>
          <div>
            <div className="text-[15px] font-semibold tracking-tight leading-none">
              Modelect
            </div>
            <div className="text-[10px] text-muted mt-1 tracking-wide uppercase">
              LLM Orchestrator
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 pb-4 overflow-y-auto">
          {GROUPS.map((g) => {
            const isOpen = !!open[g.label];
            return (
              <div key={g.label} className="mt-3 first:mt-1">
                <button
                  onClick={() => toggle(g.label)}
                  className="w-full flex items-center justify-between px-3 py-1.5 rounded-md
                    text-[10px] font-medium uppercase tracking-[0.14em] text-muted/80
                    hover:text-ink2 transition-colors"
                  aria-expanded={isOpen}
                >
                  {g.label}
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                    className={`transition-transform duration-200 ${isOpen ? "rotate-0" : "-rotate-90"}`}>
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div
                  className="overflow-hidden transition-all duration-200 ease-in-out"
                  style={{ maxHeight: isOpen ? g.items.length * 40 + 8 : 0, opacity: isOpen ? 1 : 0 }}
                >
                  <div className="space-y-0.5 pt-0.5">
                    {g.items.map((n) => (
                      <NavLink
                        key={n.to}
                        to={n.to}
                        className={({ isActive }) =>
                          `group flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition-colors ${
                            isActive
                              ? "bg-raised text-ink shadow-sm"
                              : "text-ink2 hover:bg-raised/50 hover:text-ink"
                          }`
                        }
                      >
                        {({ isActive }) => (
                          <>
                            <span className={isActive ? "text-s1" : "text-muted group-hover:text-ink2 transition-colors"}>
                              {ICONS[n.icon]}
                            </span>
                            {n.label}
                          </>
                        )}
                      </NavLink>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </nav>

        <div className="px-5 py-4 border-t border-edge flex items-center justify-between">
          <span className="text-[11px] text-muted">
            Gateway <code className="text-ink2">/v1</code>
          </span>
          <span className="chip !text-[10px]">demo · v0.6</span>
        </div>
      </aside>

      <main className="flex-1 px-8 py-7 max-w-[1240px]">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/clusters" element={<Clusters />} />
          <Route path="/models" element={<Catalog />} />
          <Route path="/recommend" element={<Recommend />} />
          <Route path="/evals" element={<Evals />} />
          <Route path="/migrate" element={<Migrate />} />
          <Route path="/deploy" element={<Deploy />} />
          <Route path="/integrate" element={<Integrate />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/playground" element={<Playground />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
