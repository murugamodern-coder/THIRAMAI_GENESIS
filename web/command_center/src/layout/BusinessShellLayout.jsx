import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";

import { fetchMyOrganizations, switchOrganization } from "../api/commandCenterApi.js";
import { hintForOrg } from "../business/orgMeta.js";
import { useCommandStore } from "../store/useCommandStore.js";
import "../styles/company-switcher.css";

const NAV = [
  { to: "dashboard", label: "Home" },
  { to: "inventory", label: "Stock" },
  { to: "billing", label: "Bills" },
  { to: "expenses", label: "Spend" },
  { to: "production", label: "Mfg" },
  { to: "tasks", label: "Tasks" },
  { to: "accounts", label: "Accounts" },
  { to: "gst", label: "GST" },
  { to: "purchase-orders", label: "Purchase" },
  { to: "payroll", label: "Payroll" },
  { to: "reports", label: "Reports" },
  { to: "profile", label: "Profile" },
];

export default function BusinessShellLayout() {
  const { orgId } = useParams();
  const navigate = useNavigate();
  const setToken = useCommandStore((s) => s.setToken);
  const orgs = useCommandStore(s => s.orgs) || [];
  const currentOrg = orgs.find(
    row => Number(row?.organization?.id) === Number(orgId)
  )?.organization;
  const [companyName, setCompanyName] = useState(currentOrg?.name || "Business OS");
  const [switchErr, setSwitchErr] = useState(null);
  const [orgRows, setOrgRows] = useState([]);
  const [showOrgMenu, setShowOrgMenu] = useState(false);
  const [switchingId, setSwitchingId] = useState(null);

  const idNum = Number(orgId);
  const base = `/business/${orgId}`;
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
        if (mine?.organization?.name) {
          setCompanyName(mine.organization.name);
        }
        setOrgRows(rows);
        if (!mine) {
          setSwitchErr("You are not a member of this organization.");
          return;
        }
        const current = Number(rows.find((r) => r.is_current)?.organization?.id);
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

  const choices = useMemo(
    () =>
      orgRows
        .map((r) => ({
          id: Number(r?.organization?.id),
          name: r?.organization?.name || `Org ${r?.organization?.id}`,
          isCurrent: Number(r?.organization?.id) === idNum,
        }))
        .filter((r) => Number.isFinite(r.id) && r.id > 0),
    [orgRows, idNum],
  );

  async function onSelectCompany(nextId) {
    if (!Number.isFinite(Number(nextId)) || Number(nextId) === idNum) {
      setShowOrgMenu(false);
      return;
    }
    setSwitchErr(null);
    setSwitchingId(nextId);
    try {
      const out = await switchOrganization(nextId);
      if (out?.access_token) setToken(out.access_token);
      setShowOrgMenu(false);
      navigate(`/business/${nextId}/dashboard`);
    } catch (e) {
      setSwitchErr(e?.response?.data?.detail || e?.message || "Could not switch organization.");
    } finally {
      setSwitchingId(null);
    }
  }

  return (
    <div className="biz-shell cc-app">
      <header className="biz-topbar">
        <div className="biz-company-switcher-wrap">
          <button
            type="button"
            className="biz-company-trigger"
            onClick={() => setShowOrgMenu((v) => !v)}
            aria-expanded={showOrgMenu}
            aria-haspopup="menu"
          >
            <span className="biz-title">{companyName}</span>
            <span className="biz-company-caret" aria-hidden="true">
              ▾
            </span>
          </button>
          <div className="cc-muted" style={{ fontSize: 12 }}>
            Business OS · org #{orgId}
            {hint?.subsidy ? " · subsidy tracking" : ""}
          </div>
          {showOrgMenu && (
            <div className="biz-company-menu" role="menu">
              {choices.map((choice) => (
                <button
                  key={choice.id}
                  type="button"
                  className={`biz-company-option ${choice.isCurrent ? "is-active" : ""}`}
                  onClick={() => onSelectCompany(choice.id)}
                  disabled={switchingId === choice.id}
                >
                  <span>{choice.name}</span>
                  {choice.isCurrent && <span className="cc-muted">Current</span>}
                </button>
              ))}
              <button
                type="button"
                className="biz-company-option"
                onClick={() => {
                  setShowOrgMenu(false);
                  navigate("/business");
                }}
              >
                View all companies
              </button>
            </div>
          )}
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