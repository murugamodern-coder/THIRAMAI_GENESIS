import { useEffect } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import {
  fetchAuthMe,
  fetchMyOrganizations,
  switchOrganization,
} from "../api/commandCenterApi.js";
import MobileBottomNav from "../components/MobileBottomNav.jsx";
import { isOnboardingDone } from "../lib/onboarding.js";
import { ROLES } from "../lib/rbac.js";
import { useCommandStore } from "../store/useCommandStore.js";

export default function ShellLayout() {
  const navigate = useNavigate();
  const token = useCommandStore((s) => s.token);
  const me = useCommandStore((s) => s.me);
  const role = useCommandStore((s) => s.role);
  const orgs = useCommandStore((s) => s.orgs);
  const setMe = useCommandStore((s) => s.setMe);
  const setOrgs = useCommandStore((s) => s.setOrgs);
  const setToken = useCommandStore((s) => s.setToken);
  const logout = useCommandStore((s) => s.logout);

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

  async function onOrgChange(e) {
    const id = Number(e.target.value);
    const current = orgs.find((o) => o.is_current)?.organization?.id;
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
    <div className="cc-app">
      <header className="cc-topbar">
        <Link className="cc-brand" to="/today" style={{ textDecoration: "none", color: "inherit" }}>
          THIRAMAI — AI Command Center
        </Link>
        <nav className="cc-nav" aria-label="Primary">
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} end to="/today">
            Today
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} end to="/dashboard">
            Dashboard
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/dashboard/inventory">
            Inventory
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/dashboard/billing">
            Billing
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/dashboard/production">
            Production
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/personal">
            Personal
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} end to="/ai">
            AI
          </NavLink>
        </nav>
        {orgs.length > 0 && (
          <label className="cc-muted" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            Organization
            <select
              className="cc-select"
              style={{ width: 220 }}
              value={String(
                orgs.find((o) => o.is_current)?.organization?.id ?? orgs[0]?.organization?.id ?? "",
              )}
              onChange={onOrgChange}
            >
              {orgs.map((row) => (
                <option key={row.organization.id} value={row.organization.id}>
                  {row.organization.name}
                  {row.is_current ? " (current)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="cc-muted" style={{ marginLeft: "auto" }}>
          {me?.email || "Signed in"}
        </span>
        <span
          className={
            role === ROLES.ADMIN
              ? "cc-pill cc-pill--success"
              : role === ROLES.OPERATOR
                ? "cc-pill cc-pill--warning"
                : "cc-pill cc-pill--neutral"
          }
          title="Your current permission role"
        >
          {role}
        </span>
        <button
          type="button"
          className="cc-btn"
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
        >
          Sign out
        </button>
      </header>
      <main className="cc-main">
        <Outlet />
      </main>
      <MobileBottomNav />
    </div>
  );
}
