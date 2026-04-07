import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fetchAnalyticsSummary,
  fetchCommandCenterSnapshot,
  fetchPendingDecisions,
  fetchProductionSummary,
} from "../api/commandCenterApi.js";
import AIAssistantPanel from "../components/dashboard/AIAssistantPanel.jsx";
import AuditPanel from "../components/dashboard/AuditPanel.jsx";
import FinancialControlTower from "../components/dashboard/FinancialControlTower.jsx";
import MissionHub from "../components/dashboard/MissionHub.jsx";
import SystemHealthPanel from "../components/dashboard/SystemHealthPanel.jsx";
import LiveStatusPill from "../components/LiveStatusPill.jsx";
import { useLiveData } from "../hooks/useLiveData.js";
import { subscribe } from "../lib/eventBus.js";
import { safeAsync } from "../lib/safeAsync.js";
import { showToastDedup } from "../lib/toastDedup.js";
import { parseInr } from "../utils/format.js";
import { setLiveSnapshot } from "../lib/runtimeContext.js";

export default function DashboardPage() {
  const [usageNote, setUsageNote] = useState(null);

  const fetchDashboard = useCallback(async () => {
    setUsageNote(null);
    const [snap, pend, pr, u] = await Promise.all([
      fetchCommandCenterSnapshot(),
      fetchPendingDecisions(80).catch(() => ({ items: [] })),
      fetchProductionSummary().catch(() => null),
      fetchAnalyticsSummary(30).catch((e) => {
        const st = e?.response?.status;
        if (st === 403) {
          setUsageNote("Usage insights are available to owner, manager, and admin roles.");
        }
        return null;
      }),
    ]);
    return {
      snapshot: snap,
      pending: pend?.items || [],
      prod: pr?.ok ? pr : null,
      usage: u?.ok ? u : null,
    };
  }, []);

  const { data, loading, error, refresh, status } = useLiveData(fetchDashboard, 10_000);

  const prevConnectedRef = useRef(true);
  const pausedToastRef = useRef(false);
  const eventRefreshRef = useRef(0);
  const coalesceRef = useRef({ pending: false, timerId: null });

  const safeRefresh = useCallback(() => {
    if (coalesceRef.current.pending) return;
    coalesceRef.current.pending = true;
    coalesceRef.current.timerId = window.setTimeout(async () => {
      try {
        await safeAsync(refresh, { toast: false })();
      } finally {
        coalesceRef.current.pending = false;
        coalesceRef.current.timerId = null;
      }
    }, 300);
  }, [refresh]);

  useEffect(() => {
    return () => {
      if (coalesceRef.current.timerId) window.clearTimeout(coalesceRef.current.timerId);
    };
  }, []);

  useEffect(() => {
    const was = prevConnectedRef.current;
    const now = status.connected === true && status.paused !== true;
    if (!was && now) {
      showToastDedup({ type: "success", message: "Connection restored" });
    }
    prevConnectedRef.current = now;
  }, [status.connected, status.paused]);

  useEffect(() => {
    if (status.paused && !pausedToastRef.current) {
      pausedToastRef.current = true;
      showToastDedup({
        type: "warning",
        message: "Live updates paused",
        actionLabel: "Retry",
        onAction: () => refresh(),
      });
    }
    if (!status.paused) pausedToastRef.current = false;
  }, [status.paused, refresh]);

  useEffect(() => {
    if (!error) return;
    const d = error?.response?.data?.detail;
    const msg = typeof d === "string" ? d : error?.message;
    if (msg) {
      showToastDedup({ type: "error", message: "Live update failed" });
    }
  }, [error]);

  useEffect(() => {
    const unsub = subscribe("dashboard:refresh", async () => {
      const now = Date.now();
      // Throttle refresh to avoid storms when multiple events fire at once.
      if (now - eventRefreshRef.current < 750) return;
      eventRefreshRef.current = now;
      safeRefresh();
      showToastDedup({ type: "info", message: "Dashboard updated" });
    });
    return unsub;
  }, [safeRefresh]);

  const snapshot = data?.snapshot || null;
  const pending = data?.pending || [];
  const prod = data?.prod || null;
  const usage = data?.usage || null;

  useEffect(() => {
    if (snapshot) setLiveSnapshot(snapshot);
  }, [snapshot]);

  const analytics = snapshot?.analytics || {};
  const revToday = parseInr(analytics?.revenue_inr?.today);
  const invCount = snapshot?.inventory_summary?.count ?? snapshot?.inventory_alerts?.count ?? 0;
  const prodOut =
    prod != null
      ? (prod.total_yield_out || 0) + (prod.total_blocks_out || 0)
      : null;
  const aiN = pending.length;

  if (loading) {
    return (
      <div>
        <h1 className="cc-page-title">AI Command Center</h1>
        <section className="cc-kpi-row" aria-label="Key performance indicators">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="cc-kpi" aria-hidden="true">
              <div className="cc-skeleton" style={{ height: 12, width: 120 }} />
              <div className="cc-skeleton" style={{ height: 28, width: 160, marginTop: 8 }} />
              <div className="cc-skeleton" style={{ height: 12, width: 90, marginTop: 8 }} />
            </div>
          ))}
        </section>
        <div className="cc-grid-2">
          <div>
            <div className="cc-card" aria-hidden="true">
              <div className="cc-skeleton" style={{ height: 16, width: 220 }} />
              <div className="cc-skeleton" style={{ height: 220, width: "100%", marginTop: 16 }} />
            </div>
            <div className="cc-card" aria-hidden="true">
              <div className="cc-skeleton" style={{ height: 16, width: 180 }} />
              <div className="cc-skeleton" style={{ height: 140, width: "100%", marginTop: 16 }} />
            </div>
            <div className="cc-card" aria-hidden="true">
              <div className="cc-skeleton" style={{ height: 16, width: 240 }} />
              <div className="cc-skeleton" style={{ height: 120, width: "100%", marginTop: 16 }} />
            </div>
          </div>
          <aside>
            <div className="cc-card" aria-hidden="true">
              <div className="cc-skeleton" style={{ height: 16, width: 140 }} />
              <div className="cc-skeleton" style={{ height: 96, width: "100%", marginTop: 16 }} />
              <div className="cc-skeleton" style={{ height: 32, width: 120, marginTop: 16 }} />
            </div>
          </aside>
        </div>
      </div>
    );
  }

  if (error && !snapshot) {
    const d = error?.response?.data?.detail;
    const msg = typeof d === "string" ? d : error?.message || "Failed to load dashboard";
    return (
      <div className="cc-card">
        <h2 className="cc-section-title">Dashboard unavailable</h2>
        <p className="cc-error" style={{ margin: "0 0 16px" }}>
          {msg}
        </p>
        <button
          type="button"
          className="cc-btn cc-btn-primary"
          onClick={() => {
            showToastDedup({ type: "info", message: "Retrying…" });
            refresh();
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  const liveDetail = useMemo(() => {
    if (status?.paused) return "Paused after repeated failures";
    if (status?.connected === false) return "Disconnected";
    return "Updating every 10s";
  }, [status?.connected, status?.paused]);

  const lastUpdatedText = useMemo(() => {
    if (!status?.lastUpdatedAt) return null;
    try {
      const d = new Date(status.lastUpdatedAt);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return null;
    }
  }, [status?.lastUpdatedAt]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 16, justifyContent: "space-between" }}>
        <h1 className="cc-page-title" style={{ marginBottom: 0 }}>
          AI Command Center
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <LiveStatusPill status={status} />
          <span className="cc-muted" style={{ fontSize: 12 }}>
            {liveDetail}
          </span>
          {lastUpdatedText && (
            <span className="cc-muted" style={{ fontSize: 12 }}>
              • Last updated: {lastUpdatedText}
            </span>
          )}
        </div>
      </div>
      <div style={{ height: 16 }} />

      <section className="cc-kpi-row" aria-label="Key performance indicators">
        <div className="cc-kpi">
          <div className="label">Revenue today</div>
          <div className="value">₹{revToday.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div>
          <div className="trend">From billing &amp; GST signals</div>
        </div>
        <div className="cc-kpi">
          <div className="label">Inventory alerts</div>
          <div className="value">{invCount}</div>
          <div className="trend">Exceptions requiring attention</div>
        </div>
        <div className="cc-kpi">
          <div className="label">Production output</div>
          <div className="value">{prodOut != null ? prodOut.toLocaleString("en-IN") : "—"}</div>
          <div className="trend">Yield + blocks (period)</div>
        </div>
        <div className="cc-kpi">
          <div className="label">AI decisions pending</div>
          <div className="value">{aiN}</div>
          <div className="trend">Human-in-the-loop approvals</div>
        </div>
      </section>

      {(usage || usageNote) && (
        <div className="cc-card">
          <h2>Product insights (30 days)</h2>
          {usageNote && !usage && <p className="cc-muted">{usageNote}</p>}
          {usage && (
            <>
              <p className="cc-muted" style={{ marginTop: -8, marginBottom: 16 }}>
                Based on <strong>usage_logs</strong> and AI decision rows — see <code>GET /analytics/summary</code>.
              </p>
              <div className="cc-kpi-row" style={{ marginBottom: 0 }}>
                <div className="cc-kpi">
                  <div className="label">Active users (any event)</div>
                  <div className="value">{usage.active_users_distinct_any_event ?? "—"}</div>
                  <div className="trend">Adoption and engagement</div>
                </div>
                <div className="cc-kpi">
                  <div className="label">Usage events</div>
                  <div className="value">{usage.usage_events_total ?? "—"}</div>
                  <div className="trend">System interactions tracked</div>
                </div>
                <div className="cc-kpi">
                  <div className="label">AI decisions (total / pending)</div>
                  <div className="value">
                    {usage.ai_decisions != null
                      ? `${usage.ai_decisions.total ?? 0} / ${usage.ai_decisions.pending ?? 0}`
                      : "—"}
                  </div>
                  <div className="trend">AI workload + HITL queue</div>
                </div>
                <div className="cc-kpi">
                  <div className="label">Alerts unread</div>
                  <div className="value">{usage.alerts_unread_count ?? "—"}</div>
                  <div className="trend">Risk and exceptions</div>
                </div>
              </div>
              <p className="cc-muted" style={{ marginTop: 16, fontSize: 12 }}>
                AI impact: approvals, executions, and failures are recorded as usage events for trend analysis.
              </p>
            </>
          )}
        </div>
      )}

      <div className="cc-grid-2">
        <div>
          <FinancialControlTower snapshot={snapshot} />
          <MissionHub items={pending} onResolved={safeRefresh} />
          <SystemHealthPanel snapshot={snapshot} />
          <AuditPanel />
        </div>
        <aside>
          <AIAssistantPanel />
        </aside>
      </div>
    </div>
  );
}
