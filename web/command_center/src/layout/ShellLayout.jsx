import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import {
  fetchAuthMe,
  fetchMyOrganizations,
  switchOrganization,
} from "../api/commandCenterApi.js";
import BuildFooter from "../components/BuildFooter.jsx";
import IncidentBanner from "../components/IncidentBanner.jsx";
import MobileBottomNav from "../components/MobileBottomNav.jsx";
import QuickActionsFAB from "../components/QuickActionsFAB.jsx";
import { isFeatureEnabled } from "../lib/featureFlags.js";
import { isOnboardingDone } from "../lib/onboarding.js";
import { useCommandStore } from "../store/useCommandStore.js";
import { useTheme } from "../context/ThemeContext.jsx";
import Avatar from "../components/ui/Avatar.jsx";
import Badge from "../components/ui/Badge.jsx";
import GlobalCommandBar from "../components/GlobalCommandBar.jsx";

export default function ShellLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const token = useCommandStore((s) => s.token);
  const me = useCommandStore((s) => s.me);
  const role = useCommandStore((s) => s.role);
  const orgs = useCommandStore((s) => s.orgs);
  const setMe = useCommandStore((s) => s.setMe);
  const setOrgs = useCommandStore((s) => s.setOrgs);
  const setToken = useCommandStore((s) => s.setToken);
  const logout = useCommandStore((s) => s.logout);
  const { theme, toggleTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [logDrawerOpen, setLogDrawerOpen] = useState(false);
  const [systemLogs, setSystemLogs] = useState([]);
  const logsWsRef = useRef(null);
  const lastOrgSwitchAt = useRef(0);

  const pathSeg = (location.pathname || "/").replace(/^\/+/, "");
  const breadcrumbs = !pathSeg ? ["Home"] : pathSeg.split("/").map((s) => s.replace(/-/g, " "));

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const [profile, list] = await Promise.all([
          fetchAuthMe().catch(() => null),
          fetchMyOrganizations().catch(() => []),
        ]);
        if (cancelled) return;
        if (profile) setMe(profile);
        setOrgs(Array.isArray(list) ? list : []);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, setMe, setOrgs]);

  useEffect(() => {
    if (!me?.id || me.id <= 0) return;
    if (!isOnboardingDone(me.id)) {
      navigate("/onboarding", { replace: true });
    }
  }, [me, navigate]);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!logDrawerOpen || !token) return undefined;
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${protocol}://${window.location.host}/ws/system/logs`;
    const ws = new WebSocket(wsUrl);
    logsWsRef.current = ws;
    ws.onopen = () => {
      try {
        ws.send(JSON.stringify({ token }));
      } catch {
        // ignore
      }
    };
    ws.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data || "{}");
        if (payload?.type !== "log" || !payload?.entry) return;
        setSystemLogs((prev) => [...prev.slice(-199), payload.entry]);
      } catch {
        // ignore malformed frames
      }
    };
    ws.onerror = () => {
      setSystemLogs((prev) => [...prev.slice(-199), { ts: new Date().toISOString(), level: "ERROR", message: "System log websocket error" }]);
    };
    return () => {
      try {
        ws.close();
      } catch {
        // ignore
      }
    };
  }, [logDrawerOpen, token]);

  const orgRows = Array.isArray(orgs) ? orgs : [];
  const selectableOrgs = orgRows.filter((row) => row?.organization?.id != null);
  const notifCount = 3;

  async function onOrgChange(e) {
    const now = Date.now();
    if (now - lastOrgSwitchAt.current < 800) return;
    lastOrgSwitchAt.current = now;
    const id = Number(e.target.value);
    const current = selectableOrgs.find((o) => o.is_current)?.organization?.id;
    if (!id || Number.isNaN(id) || id === current) return;
    try {
      const out = await switchOrganization(id);
      if (out?.access_token) setToken(out.access_token);
      window.location.hash = "#/today";
      window.location.reload();
    } catch {
      /* toast could go here */
    }
  }

  return (
    <div className={`cc-shell ${mobileMenuOpen ? "mobile-open" : ""}`}>
      <IncidentBanner />
      <aside className={`cc-sidebar ${collapsed ? "is-collapsed" : ""}`} aria-label="Primary navigation">
        <div className="cc-sidebar__brand">
          <button type="button" className="cc-btn cc-btn-ghost" aria-label="Toggle sidebar" onClick={() => setCollapsed((v) => !v)}>
            {collapsed ? "→" : "←"}
          </button>
          {!collapsed ? <span className="cc-brand">THIRAMAI</span> : null}
        </div>
        <nav className="cc-nav cc-nav--sidebar" aria-label="Primary">
          <NavLink
            className={({ isActive }) => (isActive ? "active" : undefined)}
            end
            to="/dashboard"
          >
            Central Brain
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/personal">
            Personal OS
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/os/stock">
            Stock OS
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/os/research">
            Research OS
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/os/agentic-platform">
            Agentic Platform
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/dashboard/inventory">
            Business
          </NavLink>
        </nav>
        <div className="cc-sidebar__user">
          <Avatar name={me?.email || "User"} size={collapsed ? "sm" : "md"} />
          {!collapsed ? (
            <div>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>{me?.email || "Signed in"}</p>
              <p style={{ margin: 0, fontSize: 12 }} className="cc-muted">
                {role}
              </p>
            </div>
          ) : null}
        </div>
      </aside>

      <div className="cc-shell__content">
        <header className="cc-topbar">
          <button
            type="button"
            className="cc-btn cc-btn-ghost cc-mobile-menu-btn"
            aria-label="Toggle mobile navigation"
            onClick={() => setMobileMenuOpen((v) => !v)}
          >
            ☰
          </button>
          <div className="cc-breadcrumbs" aria-label="Breadcrumb">
            {breadcrumbs.map((crumb, idx) => (
              <span key={`${crumb}-${idx}`} className="cc-muted">
                {idx > 0 ? " / " : ""}
                {crumb}
              </span>
            ))}
          </div>
          <label style={{ minWidth: 220 }}>
            <input
              className="cc-input"
              placeholder="Search... (Cmd/Ctrl+K or /)"
              aria-label="Global search"
              onFocus={(e) => {
                e.target.blur();
                window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }));
              }}
              readOnly
            />
          </label>
          <button type="button" className="cc-btn cc-btn-ghost" aria-label="Notifications">
            🔔 {notifCount > 0 ? <Badge variant="error" size="sm">{notifCount}</Badge> : null}
          </button>
          <button type="button" className="cc-btn cc-btn-ghost" onClick={() => setLogDrawerOpen((v) => !v)}>
            Terminal
          </button>
          <button type="button" className="cc-btn" onClick={toggleTheme} aria-label="Toggle theme">
            {theme === "dark" ? "Light" : "Dark"}
          </button>
          {selectableOrgs.length > 0 && (
            <select
              className="cc-select"
              style={{ width: 220 }}
              data-cc-track="org_switch"
              value={String(selectableOrgs.find((o) => o.is_current)?.organization?.id ?? selectableOrgs[0]?.organization?.id ?? "")}
              onChange={onOrgChange}
              aria-label="Organization switcher"
            >
              {selectableOrgs.map((row) => (
                <option key={row.organization.id} value={row.organization.id}>
                  {row.organization.name}
                  {row.is_current ? " (current)" : ""}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            className="cc-btn"
            data-cc-track="sign_out"
            onClick={() => {
              logout();
              navigate("/login", { replace: true });
            }}
          >
            Sign out
          </button>
        </header>
        <main
          className="cc-main"
          id="cc-main-content"
          style={{ overflowY: "auto", minHeight: 0, paddingBottom: 120 }}
        >
          <Outlet />
        </main>
        <footer className="cc-build-footer" style={{ padding: "6px 16px 10px", borderTop: "1px solid var(--cc-border, #e5e7eb)" }}>
          <BuildFooter />
        </footer>
      </div>
      {mobileMenuOpen ? (
        <button
          type="button"
          className="cc-sidebar-overlay"
          aria-label="Close navigation"
          onClick={() => setMobileMenuOpen(false)}
        />
      ) : null}
      <MobileBottomNav />
      {isFeatureEnabled("QUICK_ACTIONS_FAB") ? <QuickActionsFAB /> : null}
      <GlobalCommandBar />
      {logDrawerOpen ? (
        <aside
          style={{
            position: "fixed",
            top: 0,
            right: 0,
            width: "min(460px, 92vw)",
            height: "100vh",
            zIndex: 1190,
            background: "rgba(15, 23, 42, 0.96)",
            borderLeft: "1px solid rgba(148,163,184,0.3)",
            boxShadow: "-10px 0 30px rgba(0,0,0,0.35)",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", borderBottom: "1px solid rgba(148,163,184,0.25)" }}>
            <strong style={{ color: "#e2e8f0", fontSize: 13 }}>Live Execution Terminal</strong>
            <button type="button" className="cc-btn cc-btn-ghost" onClick={() => setLogDrawerOpen(false)}>Close</button>
          </div>
          <div style={{ overflowY: "auto", padding: 10, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12, color: "#cbd5e1" }}>
            {systemLogs.length === 0 ? <div>No logs yet. Waiting for orchestrator / auto-deploy events...</div> : null}
            {systemLogs.map((row, idx) => (
              <div key={`${row.ts || "ts"}_${idx}`} style={{ marginBottom: 8 }}>
                <div style={{ color: "#94a3b8" }}>[{row.ts || "-"}] [{row.level || "INFO"}] {row.logger || "system"}</div>
                <div>{row.message || ""}</div>
              </div>
            ))}
          </div>
        </aside>
      ) : null}
    </div>
  );
}
