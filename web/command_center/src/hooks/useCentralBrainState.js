import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchBusinessPlDaily,
  fetchBusinessSnapshot,
  fetchCommandCenterSnapshot,
  fetchMyOrganizations,
  fetchPendingDecisions,
  fetchPersonalTodayBrief,
  fetchStockMorningBrief,
  fetchStockPortfolio,
  fetchStockRealtimeStatus,
  fetchStockWatchlist,
  fetchWebsiteMeta,
} from "../api/commandCenterApi.js";
import { safeArray } from "../lib/safeData.js";

const DEFAULT_POLL_MS = 12_000;
const REQUEST_TIMEOUT_MS = 9_000;

function withTimeout(task, label, timeoutMs = REQUEST_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      reject(new Error(`${label} timed out`));
    }, timeoutMs);
    task
      .then((value) => {
        window.clearTimeout(timer);
        resolve(value);
      })
      .catch((error) => {
        window.clearTimeout(timer);
        reject(error);
      });
  });
}

function asErrorMessage(error) {
  const d = error?.response?.data?.detail;
  if (typeof d === "string" && d.trim()) return d;
  if (typeof error?.message === "string" && error.message.trim()) return error.message;
  return "Unavailable";
}

function statusFromError(error) {
  return error ? "degraded" : "healthy";
}

function asNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function buildPersonalModule(payload, error) {
  const meetings = safeArray(payload?.meetings_today);
  const alerts = safeArray(payload?.proactive_alerts);
  const habits = asNumber(payload?.habit_streak_days, 0);
  return {
    id: "personal",
    title: "Personal OS",
    route: "/os/personal",
    description: "Life automation layer for Lindy, Motion, and Recall loops.",
    liveStatus: statusFromError(error),
    statusDetail: error ? asErrorMessage(error) : "Routines and schedule intelligence active",
    quickMetrics: [
      { label: "Meetings today", value: meetings.length },
      { label: "Proactive alerts", value: alerts.length },
      { label: "Habit streak", value: habits > 0 ? `${habits} days` : "No streak" },
    ],
    agentActivity: {
      activeAgents: alerts.length,
      lastEvent: payload?.next_meeting?.title || payload?.ai_insight || "Daily brief generated",
    },
  };
}

function buildBusinessModule(snapshot, pl, error) {
  const lowStock = safeArray(snapshot?.low_stock_alerts ?? snapshot?.low_stock).length;
  const today = pl?.today && typeof pl.today === "object" ? pl.today : {};
  const net = asNumber(today?.net_inr, 0);
  const checkedIn = snapshot?.attendance_today?.checked_in_today ?? snapshot?.attendance?.checked_in_today ?? "—";
  return {
    id: "business",
    title: "Business OS",
    route: "/os/business",
    description: "ERP-grade operations across trading, manufacturing, and governance.",
    liveStatus: statusFromError(error),
    statusDetail: error ? asErrorMessage(error) : "Tenant operations synchronized",
    quickMetrics: [
      { label: "Today net", value: `₹${net.toLocaleString("en-IN")}` },
      { label: "Checked in", value: checkedIn },
      { label: "Low-stock alerts", value: lowStock },
    ],
    agentActivity: {
      activeAgents: Math.max(lowStock, 0),
      lastEvent: "Cashflow and inventory guardrails running",
    },
  };
}

function buildStockModule(watchlist, portfolio, realtime, brief, error) {
  const symbols = safeArray(watchlist?.symbols ?? watchlist);
  const positions = safeArray(portfolio?.positions);
  const marketSentiment = brief?.market_sentiment || "neutral";
  const watchCount = symbols.length;
  const alertsCount = safeArray(realtime?.alerts).length;
  const engine = {
    macro: marketSentiment,
    orderFlow: realtime?.mode || "monitoring",
    fundamentals: positions.length > 0 ? "tracked" : "warming",
    geopolitics: brief?.headline_risk || "stable",
  };
  return {
    id: "stock",
    title: "Stock OS",
    route: "/os/stock",
    description: "Market intelligence with live macro, order-flow, fundamentals, and geopolitics.",
    liveStatus: statusFromError(error),
    statusDetail: error ? asErrorMessage(error) : "Realtime market intelligence online",
    quickMetrics: [
      { label: "Watchlist", value: watchCount },
      { label: "Open positions", value: positions.length },
      { label: "Realtime mode", value: realtime?.mode || "streaming" },
    ],
    agentActivity: {
      activeAgents: Math.max(alertsCount, 1),
      lastEvent: brief?.summary || "Tick stream and risk engine active",
    },
    fourPointEngine: engine,
  };
}

function buildResearchModule(pending, snapshot, error) {
  const pendingItems = safeArray(pending?.items ?? pending);
  const highPriority = pendingItems.filter((row) => String(row?.priority || "").toLowerCase() === "high").length;
  const queued = asNumber(snapshot?.analytics?.ai_decisions?.pending ?? pendingItems.length, pendingItems.length);
  return {
    id: "research",
    title: "Research OS",
    route: "/os/research",
    description: "Mission decomposition, recursive search, synthesis, reasoning, and report delivery.",
    liveStatus: statusFromError(error),
    statusDetail: error ? asErrorMessage(error) : "Multi-agent research pipeline operational",
    quickMetrics: [
      { label: "Active missions", value: queued },
      { label: "High-priority", value: highPriority },
      { label: "Pipeline", value: "5-stage live" },
    ],
    agentActivity: {
      activeAgents: Math.max(queued, 1),
      lastEvent: "Recursive search and synthesis loop running",
    },
  };
}

function buildAgenticWebModule(meta, orgCount, error) {
  const slug = meta?.slug || "not-generated";
  const publicUrl = meta?.public_url;
  return {
    id: "agentic-web",
    title: "Agentic Web OS",
    route: "/os/agentic-platform",
    description: "Platform layer for automated product creation workflows.",
    liveStatus: statusFromError(error),
    statusDetail: error ? asErrorMessage(error) : "Build and deploy fabric ready",
    quickMetrics: [
      { label: "Organizations", value: orgCount },
      { label: "Published URL", value: publicUrl ? "Available" : "Pending" },
      { label: "Current slug", value: slug },
    ],
    agentActivity: {
      activeAgents: publicUrl ? 2 : 1,
      lastEvent: publicUrl || "Awaiting build trigger",
    },
  };
}

export function useCentralBrainState(explicitOrgId) {
  const [modules, setModules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);
  const [resolvedOrgId, setResolvedOrgId] = useState(null);

  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(
    async ({ silent = false } = {}) => {
      const rid = requestIdRef.current + 1;
      requestIdRef.current = rid;
      const firstLoad = !lastUpdatedAt;
      if (!silent && firstLoad) {
        setLoading(true);
      } else {
        setRefreshing(true);
      }

      const orgRows = await withTimeout(fetchMyOrganizations().catch(() => []), "organizations").catch(() => []);
      const orgList = safeArray(orgRows);
      const activeOrgId =
        Number(explicitOrgId) ||
        Number(resolvedOrgId) ||
        Number(orgList.find((row) => row?.is_current)?.organization?.id) ||
        Number(orgList[0]?.organization?.id) ||
        0;
      if (activeOrgId > 0) setResolvedOrgId(activeOrgId);

      const [personalResult, businessResult, stockResult, researchResult, platformResult] = await Promise.allSettled([
        (async () => {
          const payload = await withTimeout(fetchPersonalTodayBrief(null), "personal today");
          return buildPersonalModule(payload, null);
        })(),
        (async () => {
          const [snap, pl] = await Promise.all([
            withTimeout(fetchBusinessSnapshot(), "business snapshot"),
            withTimeout(fetchBusinessPlDaily(), "business pl"),
          ]);
          return buildBusinessModule(snap, pl, null);
        })(),
        (async () => {
          const [watchlist, portfolio, realtime, brief] = await Promise.all([
            withTimeout(fetchStockWatchlist(), "stock watchlist"),
            withTimeout(fetchStockPortfolio().catch(() => null), "stock portfolio"),
            withTimeout(fetchStockRealtimeStatus().catch(() => null), "stock realtime"),
            withTimeout(fetchStockMorningBrief().catch(() => null), "stock brief"),
          ]);
          return buildStockModule(watchlist, portfolio, realtime, brief, null);
        })(),
        (async () => {
          const [pending, snapshot] = await Promise.all([
            withTimeout(fetchPendingDecisions(60).catch(() => ({ items: [] })), "research queue"),
            withTimeout(fetchCommandCenterSnapshot().catch(() => null), "command center snapshot"),
          ]);
          return buildResearchModule(pending, snapshot, null);
        })(),
        (async () => {
          if (!activeOrgId) {
            return buildAgenticWebModule(null, orgList.length, new Error("No active organization"));
          }
          const meta = await withTimeout(fetchWebsiteMeta(activeOrgId).catch(() => null), "agentic web");
          return buildAgenticWebModule(meta, orgList.length, null);
        })(),
      ]);

      if (!mountedRef.current || requestIdRef.current !== rid) return;

      const nextModules = [
        personalResult.status === "fulfilled"
          ? personalResult.value
          : buildPersonalModule(null, personalResult.reason),
        businessResult.status === "fulfilled"
          ? businessResult.value
          : buildBusinessModule(null, null, businessResult.reason),
        stockResult.status === "fulfilled"
          ? stockResult.value
          : buildStockModule(null, null, null, null, stockResult.reason),
        researchResult.status === "fulfilled"
          ? researchResult.value
          : buildResearchModule(null, null, researchResult.reason),
        platformResult.status === "fulfilled"
          ? platformResult.value
          : buildAgenticWebModule(null, orgList.length, platformResult.reason),
      ];

      setModules(nextModules);
      setLastUpdatedAt(Date.now());
      const offlineCount = nextModules.filter((mod) => mod.liveStatus !== "healthy").length;
      setError(offlineCount === nextModules.length ? "All OS modules are degraded" : null);
      setLoading(false);
      setRefreshing(false);
    },
    [explicitOrgId, lastUpdatedAt, resolvedOrgId],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      refresh({ silent: true });
    }, DEFAULT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return {
    modules,
    loading,
    refreshing,
    error,
    lastUpdatedAt,
    refresh,
  };
}
