import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";

import { fetchMyOrganizations, switchOrganization } from "../api/commandCenterApi.js";
import { hintForOrg } from "../business/orgMeta.js";
import { useCommandStore } from "../store/useCommandStore.js";

const NAV = [
  { to: "dashboard", label: "Home" },
  { to: "inventory", label: "Stock" },
  { to: "billing", label: "Bills" },
  { to: "expenses", label: "Spend" },
  { to: "production", label: "Mfg" },
  { to: "tasks", label: "Tasks" },
];

export default function BusinessShellLayout() {
  const { orgId } = useParams();
  const navigate = useNavigate();
  const setToken = useCommandStore((s) => s.setToken);
  const [switchErr, setSwitchErr] = useState(null);
  const [orgName, setOrgName] = useState("");

  const idNum = Number(orgId);
  const base = useMemo(() => `/business/${orgId}`, [orgId]);
  const hint = hintForOrg(idNum);

  useEffect(() => {
    if (!orgId || Number.isNaN(idNum) || idNum < 1) {
      navigate("/dashboard", { replace: true });
      return;
    }
    let cancelled = false;
    setSwitchErr(null);
    (async () => {
      try {
        const list = await fetchMyOrganizations();
        if (cancelled) return;
        const rows = Array.isArray(list) ? list : [];
        const mine = rows.find((r) => Number(r?.organization?.id) === idNum);
        if (!mine) {
          setSwitchErr("You are not a member of this organization.");
          return;
        }
        setOrgName(mine.organization?.name || "");
        const current = rows.find((r) => r.is_current)?.organization?.id;
        if (current !== idNum) {
          const out = await switchOrganization(idNum);
          if (out?.access_token) setToken(out.access_token);
        }
      } catch (e) {
        if (!cancelled) {
          setSwitchErr(e?.response?.data?.detail || e?.message || "Could not switch organization.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orgId, idNum, navigate, setToken]);

  const title = hint?.label || orgName || `Org ${orgId}`;

  return (
    <div className="biz-shell cc-app">
      <header className="biz-topbar">
        <div>
          <div className="biz-title">{title}</div>
          <div className="cc-muted" style={{ fontSize: 12 }}>
            Business OS · org #{orgId}
            {hint?.subsidy ? " · subsidy tracking" : ""}
          </div>
        </div>
        <NavLink to="/today" className="cc-muted" style={{ fontSize: 13 }}>
          Command Center
        </NavLink>
      </header>

      {switchErr && <p className="cc-error biz-banner">{switchErr}</p>}

      <main className="biz-main">
        <Outlet context={{ orgId: idNum, base, hint }} />
      </main>

      <nav className="biz-bottom-nav" aria-label="Business sections">
        {NAV.map(({ to, label }) => (
          <NavLink
            key={to}
            to={`${base}/${to}`}
            className={({ isActive }) => (isActive ? "active" : undefined)}
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
