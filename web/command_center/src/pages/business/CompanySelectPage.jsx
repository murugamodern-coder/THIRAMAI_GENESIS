import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchMyOrganizations } from "../../api/commandCenterApi.js";

const AVATAR_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#db2777", "#8b5cf6"];

function initials(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "CO";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] || ""}${parts[1][0] || ""}`.toUpperCase();
}

function SkeletonCard() {
  return (
    <div className="cc-card" aria-hidden="true">
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <div
          className="cc-skeleton"
          style={{ width: 44, height: 44, borderRadius: 9999, flex: "0 0 auto" }}
        />
        <div style={{ flex: 1 }}>
          <div className="cc-skeleton" style={{ height: 14, width: "60%", marginBottom: 8 }} />
          <div className="cc-skeleton" style={{ height: 12, width: "35%" }} />
        </div>
      </div>
    </div>
  );
}

export default function CompanySelectPage() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [search, setSearch] = useState("");
  const [orgRows, setOrgRows] = useState([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    (async () => {
      try {
        const data = await fetchMyOrganizations(); // GET /me/organizations
        if (cancelled) return;
        setOrgRows(Array.isArray(data) ? data : []);
      } catch (e) {
        if (!cancelled) setErr(e?.response?.data?.detail || e?.message || "Could not load companies.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const orgs = useMemo(() => {
    return orgRows
      .map((row, idx) => {
        const org = row?.organization || {};
        const id = Number(org?.id);
        return {
          id,
          name: org?.name || `Organization ${id || "?"}`,
          color: AVATAR_COLORS[idx % AVATAR_COLORS.length],
        };
      })
      .filter((o) => Number.isFinite(o.id) && o.id > 0);
  }, [orgRows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return orgs;
    return orgs.filter((o) => o.name.toLowerCase().includes(q));
  }, [orgs, search]);

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px 48px" }}>
      <h1 className="cc-page-title">Select company</h1>

      <div style={{ marginBottom: 14 }}>
        <input
          className="cc-input"
          type="search"
          placeholder="Search companies…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {err && <p className="cc-error">{err}</p>}

      {loading ? (
        <div style={{ display: "grid", gap: 12 }}>
          {Array.from({ length: 4 }).map((_, idx) => (
            <SkeletonCard key={idx} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <p className="cc-muted">No companies found.</p>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 12,
          }}
        >
          {filtered.map((org) => (
            <button
              key={org.id}
              type="button"
              className="cc-card"
              onClick={() => navigate(`/business/${org.id}/dashboard`)}
              style={{ textAlign: "left", cursor: "pointer" }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 9999,
                    background: org.color,
                    display: "grid",
                    placeItems: "center",
                    color: "#fff",
                    fontWeight: 800,
                    flex: "0 0 auto",
                    userSelect: "none",
                  }}
                >
                  {initials(org.name)}
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 800, lineHeight: 1.2 }}>{org.name}</div>
                  <div className="cc-muted" style={{ fontSize: 12 }}>
                    Open Business OS
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
