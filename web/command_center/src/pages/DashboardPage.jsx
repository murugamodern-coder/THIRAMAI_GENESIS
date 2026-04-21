import { useMemo } from "react";
import { Link } from "react-router-dom";

import AIAssistantPanel from "../components/dashboard/AIAssistantPanel.jsx";
import AuditPanel from "../components/dashboard/AuditPanel.jsx";
import OSModuleTile from "../components/os/OSModuleTile.jsx";
import Card from "../components/ui/Card.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import { logRenderStart, useLayoutCommitTrace, usePostCommitTrace } from "../lib/hookDebug.js";
import { useRenderTiming } from "../lib/useRenderTiming.jsx";
import { useCentralBrainState } from "../hooks/useCentralBrainState.js";
import { useCommandStore } from "../store/useCommandStore.js";

export default function DashboardPage() {
  logRenderStart("DashboardPage");
  const orgRows = useCommandStore((s) => s.orgs);
  const activeOrgId = useMemo(() => {
    const rows = Array.isArray(orgRows) ? orgRows : [];
    const current = rows.find((row) => row?.is_current)?.organization?.id;
    const fallback = rows[0]?.organization?.id;
    return Number(current || fallback || 0);
  }, [orgRows]);
  const { modules, loading, refreshing, error, lastUpdatedAt, refresh } = useCentralBrainState(activeOrgId);

  useLayoutCommitTrace("DashboardPage");
  usePostCommitTrace("DashboardPage");
  useRenderTiming("DashboardPage");

  const lastUpdatedText = useMemo(() => {
    if (!lastUpdatedAt) return "Never";
    try {
      const d = new Date(lastUpdatedAt);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return "Unknown";
    }
  }, [lastUpdatedAt]);

  const healthSummary = useMemo(() => {
    const healthy = modules.filter((mod) => mod.liveStatus === "healthy").length;
    const degraded = modules.filter((mod) => mod.liveStatus !== "healthy").length;
    const activeAgents = modules.reduce(
      (sum, mod) => sum + Number(mod?.agentActivity?.activeAgents || 0),
      0,
    );
    return {
      healthy,
      degraded,
      activeAgents,
      total: modules.length,
    };
  }, [modules]);

  const modulePriorityFeed = useMemo(
    () =>
      modules
        .map((mod) => ({
          id: mod.id,
          title: mod.title,
          status: mod.liveStatus,
          summary: mod.agentActivity?.lastEvent || mod.statusDetail,
          route: mod.route,
        }))
        .sort((a, b) => {
          const rankA = a.status === "healthy" ? 1 : 0;
          const rankB = b.status === "healthy" ? 1 : 0;
          return rankA - rankB;
        }),
    [modules],
  );

  if (loading) {
    return (
      <div className="cc-card" aria-busy="true">
        <h2 className="cc-section-title">Central Brain is booting</h2>
        <div className="ui-skeleton" style={{ height: 260 }} aria-hidden="true" />
      </div>
    );
  }

  if (error && modules.length === 0) {
    return (
      <div className="cc-card">
        <h2 className="cc-section-title">Central Brain unavailable</h2>
        <p className="cc-error" style={{ margin: "0 0 16px" }}>
          {error}
        </p>
        <button type="button" className="cc-btn cc-btn-primary" onClick={() => refresh()}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div>
      <Card
        variant="gradient"
        glass
        title="THIRAMAI Central Brain"
        subtitle="Operating-system control plane for Personal, Business, Stock, Research, and Agentic Web modules."
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="cc-muted" style={{ fontSize: 12 }}>
              Last sync: {lastUpdatedText}
            </span>
            <button type="button" className="cc-btn cc-btn-primary" onClick={() => refresh()}>
              {refreshing ? "Syncing..." : "Sync now"}
            </button>
          </div>
        }
      >
        <div className="cc-kpi-row" style={{ marginBottom: 0 }}>
          <div className="cc-kpi">
            <div className="label">Modules healthy</div>
            <div className="value">
              {healthSummary.healthy}/{healthSummary.total}
            </div>
            <div className="trend">Central availability</div>
          </div>
          <div className="cc-kpi">
            <div className="label">Modules degraded</div>
            <div className="value">{healthSummary.degraded}</div>
            <div className="trend">Requires attention</div>
          </div>
          <div className="cc-kpi">
            <div className="label">Active agents</div>
            <div className="value">{healthSummary.activeAgents}</div>
            <div className="trend">Running automations</div>
          </div>
          <div className="cc-kpi">
            <div className="label">Fast actions</div>
            <div className="value">
              <Link to="/today">Today</Link>
            </div>
            <div className="trend">Open orchestrator</div>
          </div>
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
        {modules.map((mod) => (
          <OSModuleTile key={mod.id} module={mod} />
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.35fr 1fr", gap: 16, marginTop: 16 }}>
        <div style={{ minWidth: 0 }}>
          <Card title="Agent visibility">
            {modulePriorityFeed.length === 0 ? (
              <EmptyState title="No module telemetry" description="Central Brain will populate once module adapters report health." />
            ) : (
              <ul style={{ margin: 0, paddingLeft: 16, display: "grid", gap: 10 }}>
                {modulePriorityFeed.map((row) => (
                  <li key={row.id} style={{ fontSize: 14 }}>
                    <strong>{row.title}</strong> ({row.status}) — {row.summary}{" "}
                    <Link to={row.route} style={{ marginLeft: 8 }}>
                      Open
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Research pipeline">
            <p className="cc-muted" style={{ marginTop: 0 }}>
              Mission Decomposition → Recursive Search → Synthesis → Reasoning → Report
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 8 }}>
              {["Decompose", "Search", "Synthesize", "Reason", "Report"].map((step) => (
                <div key={step} className="cc-card" style={{ margin: 0, padding: 8, textAlign: "center" }}>
                  <div style={{ fontWeight: 700, fontSize: 12 }}>{step}</div>
                  <div className="cc-muted" style={{ fontSize: 11, marginTop: 4 }}>
                    active
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
        <aside style={{ minWidth: 0 }}>
          <AIAssistantPanel />
          <AuditPanel />
        </aside>
      </div>
    </div>
  );
}
