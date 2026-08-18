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
import Tokenomics from "./pages/Tokenomics";
import Login from "./pages/Login";
import MyUsage from "./pages/MyUsage";

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
  tokenomics: (
    <Icon>
      <circle cx="12" cy="12" r="10" />
      <path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8" />
      <path d="M12 18V6" />
    </Icon>
  ),
  usage: (
    <Icon>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" />
    </Icon>
  ),
  settings: (
    <Icon>
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </Icon>
  ),
};

type NavGroup = { label: string; items: { to: string; label: string; icon: string }[] };

const DECIDE: NavGroup = {
  label: "Decide",
  items: [
    { to: "/models", label: "Model Catalog", icon: "catalog" },
    { to: "/recommend", label: "Recommend", icon: "recommend" },
    { to: "/evals", label: "Evals", icon: "evals" },
    { to: "/compare", label: "Compare", icon: "compare" },
  ],
};
const DEPLOY: NavGroup = {
  label: "Deploy",
  items: [
    { to: "/migrate", label: "Migrate from Cloud", icon: "migrate" },
    { to: "/deploy", label: "Deployments", icon: "deploy" },
  ],
};
const INTEGRATE: NavGroup = {
  label: "Integrate",
  items: [
    { to: "/integrate", label: "Integrate & Verify", icon: "integrate" },
    { to: "/playground", label: "Playground", icon: "playground" },
  ],
};

const ADMIN_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
      { to: "/clusters", label: "GPU Fleet", icon: "fleet" },
    ],
  },
  DECIDE, DEPLOY, INTEGRATE,
  {
    label: "Govern",
    items: [
      { to: "/tokenomics", label: "Tokenomics", icon: "tokenomics" },
      { to: "/settings", label: "Settings", icon: "settings" },
    ],
  },
];

const USER_GROUPS: NavGroup[] = [
  DECIDE, DEPLOY, INTEGRATE,
  { label: "Govern", items: [{ to: "/usage", label: "My Usage", icon: "usage" }] },
];

const GROUPS = ADMIN_GROUPS; // superset, used for open-state defaults

interface Me {
  username: string;
  role: "admin" | "user";
  team_id: string | null;
  demo_seed?: boolean;
}

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
  const [me, setMe] = useState<Me | null | "loading">("loading");

  const loadMe = () =>
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));

  useEffect(() => {
    loadMe();
  }, []);

  // the group holding the current page always opens, so the active
  // item can never be hidden behind a collapsed section
  useEffect(() => {
    const active = GROUPS.find((g) => g.items.some((i) => i.to === location.pathname));
    if (active && !open[active.label]) {
      setOpen((o) => ({ ...o, [active.label]: true }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  if (me === "loading") {
    return <div className="min-h-screen bg-page" />;
  }
  if (me === null) {
    return <Login onLogin={loadMe} />;
  }

  const isAdmin = me.role === "admin";
  const groups = isAdmin ? ADMIN_GROUPS : USER_GROUPS;
  const home = isAdmin ? "/dashboard" : "/models";

  const AdminOnly = ({ children }: { children: ReactNode }) =>
    isAdmin ? <>{children}</> : (
      <div className="card text-sm text-muted max-w-md">
        This area requires an administrator account.
      </div>
    );

  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    setMe(null);
  };

  const crumb = (() => {
    for (const g of [...ADMIN_GROUPS, ...USER_GROUPS])
      for (const i of g.items)
        if (i.to === location.pathname) return { group: g.label, page: i.label };
    return null;
  })();

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
        <div className="px-5 pt-5 pb-4">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-s1 to-[#1c5cab] grid place-items-center text-white font-semibold text-sm shadow-lg shadow-s1/25 ring-1 ring-white/10">
              M
            </div>
            <div>
              <div className="text-[15px] font-semibold tracking-tight leading-none">
                Modelect
              </div>
              <div className="text-[10px] text-muted mt-1 tracking-[0.14em] uppercase">
                LLM Orchestrator
              </div>
            </div>
          </div>
          <div className="mt-4 h-px bg-gradient-to-r from-s1/70 via-s3/40 to-transparent" />
        </div>

        <nav className="flex-1 px-3 pb-4 overflow-y-auto">
          {groups.map((g) => {
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

        <div className="border-t border-edge">
          <div className="h-px bg-gradient-to-r from-s1/50 via-s3/30 to-transparent" />
          <div className="px-5 py-3 flex items-center justify-between">
            <span className="text-[10px] text-muted tracking-wide">© 2026 Modelect</span>
            <span className="chip !text-[10px] !py-0">v1.7</span>
          </div>
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-h-screen min-w-0">
        <header className="sticky top-0 z-20 border-b border-edge bg-page/80 backdrop-blur-md">
          <div className="h-[2px] w-full bg-gradient-to-r from-s1 via-s3/70 to-transparent" />
          <div className="flex items-center justify-between px-8 h-12">
            <div className="text-xs text-muted flex items-center min-w-0">
              {crumb ? (
                <>
                  <span className="uppercase tracking-[0.12em] text-[10px]">{crumb.group}</span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2" className="mx-2 text-grid shrink-0">
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                  <span className="text-ink2 truncate">{crumb.page}</span>
                </>
              ) : (
                <span className="text-ink2">Modelect</span>
              )}
            </div>
            <div className="flex items-center gap-2.5 shrink-0">
              {me.demo_seed === false ? (
                <span className="chip !text-[10px]" title="no seeded history — every number comes from real traffic">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-good mr-1.5 animate-pulse" />
                  live data
                </span>
              ) : (
                <span className="chip !text-[10px]" title="includes seeded demo history — set DEMO_SEED=0 for real traffic only">
                  demo data
                </span>
              )}
              <span className={`chip !text-[10px] ${isAdmin ? "border-s1/50 text-s1" : ""}`}>
                {isAdmin ? "admin" : "user"}
              </span>
              <div className="flex items-center gap-2 pl-2.5 border-l border-edge">
                <div className="h-7 w-7 rounded-full bg-raised border border-edge grid place-items-center text-[11px] font-medium text-ink2 uppercase">
                  {me.username.slice(0, 1)}
                </div>
                <span className="text-xs text-ink2 max-w-[140px] truncate">{me.username}</span>
                <button onClick={logout} title="sign out"
                  className="text-muted hover:text-ink transition-colors p-1">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <path d="m16 17 5-5-5-5" />
                    <path d="M21 12H9" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </header>

        <div className="flex-1 px-8 py-7 max-w-[1240px] w-full">
        <Routes>
          <Route path="/" element={<Navigate to={home} replace />} />
          <Route path="/dashboard" element={<AdminOnly><Dashboard /></AdminOnly>} />
          <Route path="/clusters" element={<AdminOnly><Clusters /></AdminOnly>} />
          <Route path="/models" element={<Catalog />} />
          <Route path="/recommend" element={<Recommend />} />
          <Route path="/evals" element={<Evals />} />
          <Route path="/migrate" element={<Migrate />} />
          <Route path="/deploy" element={<Deploy />} />
          <Route path="/integrate" element={<Integrate />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/playground" element={<Playground />} />
          <Route path="/usage" element={<MyUsage />} />
          <Route path="/tokenomics" element={<AdminOnly><Tokenomics /></AdminOnly>} />
          <Route path="/settings" element={<AdminOnly><Settings /></AdminOnly>} />
        </Routes>
        </div>

        <footer className="border-t border-edge px-8 py-4 flex flex-wrap items-center justify-between gap-3">
          <span className="text-[11px] text-muted">
            Modelect<span className="text-s1">.</span> — decide · deploy · integrate · govern
          </span>
          <div className="flex items-center gap-2 text-[11px]">
            <a href="/docs" target="_blank" rel="noreferrer" className="chip hover:!text-ink transition">API docs</a>
            <span className="chip">gateway /v1 · OpenAI-compatible</span>
            <span className="chip">v1.7</span>
          </div>
        </footer>
      </main>
    </div>
  );
}
