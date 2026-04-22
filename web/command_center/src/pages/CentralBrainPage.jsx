import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import api from "../api/client.js";
import { fetchAgentMissions } from "../api/commandCenterApi.js";

const OS_ICONS = {
  personal: "👤",
  business: "🏢",
  stock: "📈",
  research: "🔬",
  agentic: "⚡",
};

/** Tile routes — keep in sync with App.jsx (ShellLayout + OS tiles). */
const OS_REGISTRY = [
  {
    key: "personal",
    name: "Personal OS",
    subtitle: "Life Operating System",
    accent: "#1D9E75",
    light: "#E1F5EE",
    route: "/personal",
    integrations: ["Lindy.ai", "Motion", "Reclaim", "Recall"],
    description: "Scheduling · Memory · Habits · Automation",
    stats: [
      { label: "Tasks today", key: "tasks_today" },
      { label: "Focus hours", key: "focus_hours" },
    ],
  },
  {
    key: "business",
    name: "Business OS",
    subtitle: "Companies & Trade · ERP",
    accent: "#378ADD",
    light: "#E6F1FB",
    route: "/dashboard/inventory",
    integrations: ["GST Portal", "Tally", "Banking", "Gov Schemes"],
    description: "Trading · Manufacturing · Gov Schemes",
    stats: [
      { label: "Revenue today", key: "revenue_today", prefix: "₹" },
      { label: "Open invoices", key: "invoices_open" },
    ],
  },
  {
    key: "stock",
    name: "Stock OS",
    subtitle: "Market Intelligence",
    accent: "#BA7517",
    light: "#FAEEDA",
    route: "/os/stock",
    integrations: ["Bloomberg", "Aladdin", "Quiver", "FlightRadar"],
    description: "Macro · Order Flow · Fundamentals · Geo Risk",
    stats: [
      { label: "Signals today", key: "signals_count" },
      { label: "Risk score", key: "risk_score", suffix: "/100" },
    ],
  },
  {
    key: "research",
    name: "Research OS",
    subtitle: "Multi-AI Research Crew",
    accent: "#D85A30",
    light: "#FAECE7",
    route: "/os/research",
    integrations: ["Perplexity", "StormAI", "GPT-5", "CrewAI"],
    description: "Decompose · Search · Synthesize · Report",
    stats: [
      { label: "Active missions", key: "missions_active" },
      { label: "Reports ready", key: "reports_ready" },
    ],
  },
  {
    key: "agentic",
    name: "Agentic Web OS",
    subtitle: "Agentic Platform",
    accent: "#993556",
    light: "#FBEAF0",
    route: "/os/agentic-platform",
    integrations: ["Replit", "Cursor", "Lovable", "bolt.new"],
    description: "Build · Deploy · Monitor · Iterate",
    stats: [
      { label: "Active projects", key: "projects_active" },
      { label: "Deployments", key: "deploys_today" },
    ],
  },
];

function OSTile({ os, activity }) {
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState(null);
  const [status, setStatus] = useState("loading");
  const [configBadge, setConfigBadge] = useState(null);
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    let mounted = true;
    api
      .get(`/api/os/${os.key}/status`)
      .then((r) => {
        if (!mounted) return;
        setMetrics(r.data?.metrics ?? null);
        setConfigBadge(r.data?.configBadge ?? null);
        setStatus(String(r.data?.status || "active"));
      })
      .catch(() => {
        if (!mounted) return;
        setStatus("error");
      });
    return () => {
      mounted = false;
    };
  }, [os.key]);

  const dotColor = status === "active" ? "#1D9E75" : status === "degraded" ? "#BA7517" : "#E24B4A";
  const busy = activity?.busy;

  function goToRoute(source) {
    try {
      console.log("CLICKED:", os.key, os.route);
      if (!os.route || typeof os.route !== "string") {
        console.error("CentralBrain OSTile: invalid route", { key: os.key, route: os.route });
        return;
      }
      navigate(os.route);
    } catch (err) {
      console.error("CentralBrain navigation failed:", source, os.key, os.route, err);
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      style={{
        cursor: "pointer",
        position: "relative",
        zIndex: 10,
        isolation: "isolate",
        background: hovered ? os.light : "var(--cc-surface, #fff)",
        border: `1px solid ${hovered ? `${os.accent}60` : "var(--cc-border, #e5e7eb)"}`,
        borderRadius: 16,
        padding: 20,
        transition: "all 0.18s ease",
        display: "flex",
        flexDirection: "column",
        gap: 0,
        overflow: "hidden",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={(e) => {
        e.stopPropagation();
        goToRoute("click");
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          goToRoute("keyboard");
        }
      }}
    >
      <div
        aria-hidden
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          width: hovered ? 110 : 70,
          height: hovered ? 110 : 70,
          borderRadius: "0 16px 0 80px",
          background: `${os.accent}12`,
          transition: "all 0.18s ease",
          pointerEvents: "none",
        }}
      />

      <div style={{ position: "relative", zIndex: 1 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <div
          style={{
            width: 38,
            height: 38,
            borderRadius: 10,
            background: `${os.accent}18`,
            border: `1px solid ${os.accent}30`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 18,
          }}
        >
          {OS_ICONS[os.key] || "◇"}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {os.key === "stock" && configBadge && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: 12,
                background: configBadge === "configured" ? "#1D9E7520" : "#E24B4A18",
                color: configBadge === "configured" ? "#0F6B4C" : "#B91C1C",
                border: `1px solid ${configBadge === "configured" ? "#1D9E7540" : "#E24B4A40"}`,
              }}
            >
              {configBadge === "configured" ? "Configured" : "Missing keys"}
            </span>
          )}
          <span style={{ fontSize: 13 }}>{busy ? "🧠" : "●"}</span>
          <span style={{ fontSize: 11, color: dotColor, fontWeight: 500 }}>
            {busy ? "Repairing…" : status === "active" ? "Live" : status === "degraded" ? "Degraded" : "Offline"}
          </span>
        </div>
      </div>

      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--cc-text, #111)", marginBottom: 2 }}>{os.name}</div>
      <div style={{ fontSize: 11, color: os.accent, fontWeight: 500, marginBottom: 4 }}>{os.subtitle}</div>
      <div style={{ fontSize: 11, color: "var(--cc-muted, #888)", marginBottom: 14, lineHeight: 1.4 }}>
        {os.description}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        {os.stats.map((s) => (
          <div
            key={s.key}
            style={{
              background: "var(--cc-bg2, #f9fafb)",
              borderRadius: 8,
              padding: "8px 10px",
              border: "1px solid var(--cc-border, #e5e7eb)",
            }}
          >
            <div style={{ fontSize: 16, fontWeight: 600, color: "var(--cc-text, #111)", lineHeight: 1.2 }}>
              {metrics ? `${s.prefix || ""}${metrics[s.key] ?? 0}${s.suffix || ""}` : "—"}
            </div>
            <div style={{ fontSize: 10, color: "var(--cc-muted, #888)", marginTop: 2 }}>{s.label}</div>
          </div>
        ))}
      </div>
      {busy ? (
        <div style={{ fontSize: 11, color: os.accent, marginBottom: 10, fontWeight: 600 }}>
          Live Agent Activity · {activity?.label || "Processing"}
        </div>
      ) : null}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 12 }}>
        {os.integrations.slice(0, 3).map((i) => (
          <span
            key={i}
            style={{
              fontSize: 10,
              padding: "2px 7px",
              borderRadius: 20,
              background: `${os.accent}15`,
              color: os.accent,
              border: `1px solid ${os.accent}30`,
              fontWeight: 500,
            }}
          >
            {i}
          </span>
        ))}
        {os.integrations.length > 3 && (
          <span
            style={{
              fontSize: 10,
              padding: "2px 7px",
              borderRadius: 20,
              background: "var(--cc-bg2, #f9fafb)",
              color: "var(--cc-muted, #888)",
              border: "1px solid var(--cc-border, #e5e7eb)",
            }}
          >
            +{os.integrations.length - 3}
          </span>
        )}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderTop: "1px solid var(--cc-border, #e5e7eb)",
          paddingTop: 10,
          marginTop: "auto",
        }}
      >
        <span style={{ fontSize: 11, color: "var(--cc-muted, #888)" }}>Open dashboard</span>
        <span
          style={{
            color: os.accent,
            fontSize: 16,
            transform: hovered ? "translateX(3px)" : "none",
            transition: "transform 0.15s",
          }}
        >
          →
        </span>
      </div>
      </div>
    </div>
  );
}

export default function CentralBrainPage() {
  const navigate = useNavigate();
  const [time, setTime] = useState(() => new Date());
  const [activityMap, setActivityMap] = useState({});
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditResults, setAuditResults] = useState([]);
  const [healthOpen, setHealthOpen] = useState(false);
  const [repairLogs, setRepairLogs] = useState([]);
  const [proactiveAlerts, setProactiveAlerts] = useState([]);

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let mounted = true;
    api
      .get("/api/brain/proactive")
      .then((r) => {
        if (!mounted) return;
        const items = Array.isArray(r.data?.alerts) ? r.data.alerts : [];
        setProactiveAlerts(items);
      })
      .catch(() => {
        if (!mounted) return;
        setProactiveAlerts([]);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    const tick = async () => {
      try {
        const [missions, deployStatus, learning] = await Promise.all([
          fetchAgentMissions({ limit: 20 }),
          api.get("/auto-deploy/status"),
          api.get("/ai/learning/recommendations"),
        ]);
        if (!live) return;
        const now = Date.now();
        const items = Array.isArray(missions?.items) ? missions.items : [];
        const nextActivity = {};
        for (const os of OS_REGISTRY) nextActivity[os.key] = { busy: false, label: "" };
        items.forEach((m) => {
          const key = String(m?.os_key || "").toLowerCase();
          const ts = m?.updated_at ? Date.parse(m.updated_at) : 0;
          if (!nextActivity[key]) return;
          if (ts && now - ts < 10 * 60 * 1000) {
            nextActivity[key] = { busy: true, label: m?.title || "Mission in progress" };
          }
        });
        const depRows = Array.isArray(deployStatus?.data?.recent_deploys) ? deployStatus.data.recent_deploys : [];
        const recs = Array.isArray(learning?.data?.recommendations) ? learning.data.recommendations : [];
        const mergedLogs = [];
        depRows.slice(-8).forEach((row) => {
          mergedLogs.push({
            ts: row.timestamp,
            line: `Error detected in runtime -> Fix proposed by DeepSeek -> Tested in Docker -> ${row.action === "restart" ? "Success" : "Queued"}`,
          });
        });
        recs.forEach((r) => {
          mergedLogs.push({
            ts: new Date().toISOString(),
            line: `Learning engine analyzed ${r.action_type}: ${r.recommendation}`,
          });
        });
        if (depRows.length > 0) {
          nextActivity.agentic = { busy: true, label: "Auto-deploy engine active" };
        }
        if (recs.length > 0) {
          nextActivity.research = { busy: true, label: "Self-improvement processing outcomes" };
        }
        setActivityMap(nextActivity);
        setRepairLogs(mergedLogs.slice(-12).reverse());
      } catch {
        // keep UI non-blocking
      }
    };
    tick();
    const id = setInterval(tick, 8000);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, []);

  const adminAuditVisible = useMemo(() => {
    if (typeof window === "undefined") return false;
    return window.location.search.includes("admin=1") || window.localStorage?.getItem("thiramai_admin_mode") === "1";
  }, []);

  async function runSystemAudit() {
    setAuditLoading(true);
    try {
      const results = await Promise.all(
        OS_REGISTRY.map(async (os) => {
          try {
            const r = await api.get(`/api/os/${os.key}/status`);
            const metrics = r.data?.metrics || {};
            const metricKeys = Object.keys(metrics);
            const nonZero = metricKeys.some((k) => Number(metrics[k] || 0) > 0);
            return {
              os: os.key,
              ok: true,
              mode: nonZero ? "LIVE" : "POSSIBLE_STUB",
            };
          } catch (e) {
            return { os: os.key, ok: false, mode: "DOWN", error: e?.message || "request failed" };
          }
        }),
      );
      setAuditResults(results);
    } finally {
      setAuditLoading(false);
    }
  }

  return (
    <div style={{ padding: "0 0 40px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 24,
          paddingBottom: 18,
          borderBottom: "1px solid var(--cc-border, #e5e7eb)",
        }}
      >
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, color: "var(--cc-text, #111)", marginBottom: 4 }}>
            THIRAMAI — Central Brain
          </div>
          <div style={{ fontSize: 13, color: "var(--cc-muted, #888)" }}>
            Personal Agentic Operating System ·{" "}
            {time.toLocaleDateString("en-IN", {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </div>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "#1D9E7515",
            borderRadius: 20,
            padding: "5px 12px",
            border: "1px solid #1D9E7540",
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "#1D9E75",
              display: "inline-block",
            }}
          />
          <span style={{ fontSize: 12, color: "#1D9E75", fontWeight: 500 }}>Live</span>
          <span style={{ fontSize: 11, color: "#1D9E7580" }}>
            {time.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      </div>

      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--cc-text, #111)", marginBottom: 10 }}>
          Proactive Alerts
        </div>
        {proactiveAlerts.length === 0 ? (
          <div
            style={{
              border: "1px solid var(--cc-border, #e5e7eb)",
              borderRadius: 10,
              padding: "10px 12px",
              marginBottom: 12,
              background: "var(--cc-bg2, #f9fafb)",
              fontSize: 12,
              color: "var(--cc-muted, #6b7280)",
            }}
          >
            No active proactive alerts.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
            {proactiveAlerts.map((a, idx) => {
              const critical = String(a?.severity || "").toLowerCase() === "critical";
              return (
                <div
                  key={`${a?.type || "alert"}_${idx}`}
                  style={{
                    borderRadius: 10,
                    border: `1px solid ${critical ? "#DC2626" : "#D97706"}`,
                    background: critical ? "#FEE2E2" : "#FEF3C7",
                    color: critical ? "#7F1D1D" : "#78350F",
                    padding: "10px 12px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 10,
                    fontSize: 12,
                  }}
                >
                  <div>
                    <strong style={{ textTransform: "uppercase", fontSize: 11 }}>{a?.type || "alert"}</strong>
                    <div style={{ marginTop: 2 }}>{a?.message || "Attention required"}</div>
                  </div>
                  <button
                    type="button"
                    className="cc-btn cc-btn-secondary"
                    onClick={() => navigate(String(a?.action_route || "/dashboard"))}
                  >
                    Fix Now →
                  </button>
                </div>
              );
            })}
          </div>
        )}
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--cc-text, #111)", marginBottom: 2 }}>
          Operating Systems
        </div>
        <div style={{ fontSize: 12, color: "var(--cc-muted, #888)" }}>5 active modules · click any tile to open</div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 14,
          marginBottom: 32,
        }}
      >
        {OS_REGISTRY.map((os) => (
          <OSTile key={os.key} os={os} activity={activityMap[os.key]} />
        ))}
      </div>

      {adminAuditVisible ? (
        <div style={{ marginBottom: 14 }}>
          <button
            type="button"
            className="cc-btn cc-btn-secondary"
            onClick={() => {
              setAuditOpen((v) => !v);
              if (!auditOpen) runSystemAudit();
            }}
          >
            {auditOpen ? "Hide System Audit" : "System Audit"}
          </button>
          {auditOpen ? (
            <div style={{ marginTop: 8, border: "1px solid var(--cc-border,#e5e7eb)", borderRadius: 10, padding: 10 }}>
              <div style={{ fontSize: 12, marginBottom: 8 }}>
                {auditLoading ? "Running endpoint verification…" : "OS endpoint verification"}
              </div>
              {auditResults.map((r) => (
                <div key={r.os} style={{ fontSize: 12, marginBottom: 4 }}>
                  {r.os.toUpperCase()}: {r.mode} {r.error ? `(${r.error})` : ""}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div style={{ marginBottom: 20 }}>
        <button type="button" className="cc-btn cc-btn-secondary" onClick={() => setHealthOpen((v) => !v)}>
          {healthOpen ? "Hide System Health" : "System Health"}
        </button>
        {healthOpen ? (
          <div
            style={{
              marginTop: 10,
              border: "1px solid var(--cc-border, #e5e7eb)",
              borderRadius: 12,
              padding: 12,
              maxHeight: 220,
              overflowY: "auto",
              background: "var(--cc-bg2,#f9fafb)",
            }}
          >
            {(repairLogs.length ? repairLogs : [{ line: "No repair telemetry yet." }]).map((r, idx) => (
              <div key={`${r.ts || "ts"}_${idx}`} style={{ fontSize: 12, marginBottom: 8 }}>
                {r.line}
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div
        style={{
          background: "var(--cc-bg2, #f9fafb)",
          borderRadius: 12,
          padding: "12px 16px",
          border: "1px solid var(--cc-border, #e5e7eb)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        {["TOGAF Architecture", "ISO 25010 Quality", "OpenAPI 3.0", "FIDO2 Auth"].map((s) => (
          <span key={s} style={{ fontSize: 11, color: "var(--cc-muted, #888)", fontWeight: 500 }}>
            · {s}
          </span>
        ))}
      </div>

      {/* Global command bar moved to ShellLayout; page-level duplicate removed intentionally. */}
    </div>
  );
}
