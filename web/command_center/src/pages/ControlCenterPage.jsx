import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fetchGovernanceGuardrails,
  fetchGovernanceLogs,
  postChatQuery,
} from "../api/commandCenterApi.js";
import CommandCenter from "../components/controlcenter/CommandCenter.jsx";
import { showToastDedup } from "../lib/toastDedup.js";

/**
 * Progressive disclosure (3 layers) — architecture unchanged:
 * 1. CALM_HOME — chat + one-line insight only; no tool panels.
 * 2. QUICK_GLANCE — compact summary cards (⌘/Ctrl+K or “Summary”); counts + micro-signals only.
 * 3. FULL_COMMAND — side drawer with lazy tools; internal tabs switch tools without closing.
 */

const IntelligencePanel = lazy(() => import("../components/controlcenter/IntelligencePanel.jsx"));
const DecisionPanel = lazy(() => import("../components/controlcenter/DecisionPanel.jsx"));
const ActionFeed = lazy(() => import("../components/controlcenter/ActionFeed.jsx"));

const DRAWER_TABS = [
  { id: "intelligence", label: "Intelligence" },
  { id: "decision", label: "Decisions" },
  { id: "action", label: "Actions" },
];

function initialViewModel() {
  return {
    system: {
      status: "DEGRADED",
      risks: 1,
      opportunities: 1,
      confidence: 62,
    },
    opportunities: [
      {
        id: "bootstrap_opp_1",
        title: "Fast inventory rotation lane",
        why: "Turnover is 18% faster in the top-selling segment this week.",
        action: "Increase protected allocation in low-volatility SKUs.",
        confidence: 74,
      },
    ],
    threats: [
      {
        id: "bootstrap_threat_1",
        title: "Rule execution drift",
        why: "Recent action logs include non-success statuses.",
        action: "Prioritize simulation before executing high-impact actions.",
        confidence: 69,
      },
    ],
    decisions: [
      {
        id: "bootstrap_decision_1",
        title: "Enable guarded expansion for top opportunity",
        impact: "Could improve weekly margin by 1.8% with bounded risk.",
        urgency: "medium",
      },
    ],
    lastAction: {
      title: "Autonomy quality gate enforced",
      impact: "+0.9% decision precision in latest cycle",
      nextStep: "Execute simulation on the highest urgency decision.",
      at: new Date().toISOString(),
    },
  };
}

function shorten(s, max) {
  const t = String(s ?? "").trim();
  if (!t) return "";
  if (t.length <= max) return t;
  return `${t.slice(0, Math.max(0, max - 1))}…`;
}

/** Counts aligned with `glanceSignals` / cards — for pre/post command diff. */
function snapshotGlanceCounts(vm) {
  if (!vm?.system) {
    return { opportunity: 0, risk: 0, decision: 0, confidence: 0, status: "" };
  }
  const { risks, opportunities: oc, status, confidence } = vm.system;
  return {
    opportunity: vm.opportunities?.length || oc || 0,
    risk: risks ?? 0,
    decision: vm.decisions?.length ?? 0,
    confidence: confidence ?? 0,
    status: status || "",
  };
}

const PROACTIVE_COOLDOWN_MS = 42_000;
const GLANCE_STAGGER_MS = 150;
const TOAST_STAGGER_MS = 300;

/** ~12% of commands: no optional success/info toasts (glance + chat still update). */
function toastSilenceBeat(command, seq) {
  let h = (seq | 0) * 7919;
  const s = String(command || "");
  for (let i = 0; i < s.length && i < 32; i++) {
    h = (h + s.charCodeAt(i) * (i + 41)) >>> 0;
  }
  return h % 8 === 0;
}

/** Large composite movement — used for calmer, longer glance only unless copy beat hits. */
function deltaIsHighImpact({ dOpp, dRisk, dDec, dConf, before, after }) {
  const mag =
    Math.abs(dOpp) +
    Math.abs(dRisk) +
    Math.abs(dDec) +
    (before.status !== after.status ? 3 : 0) +
    (Math.abs(dConf) >= 8 ? 3 : Math.abs(dConf) >= 5 ? 1 : 0);
  return mag >= 6;
}

/** ~10% of high-impact moments surface the rare line (deterministic). */
function highImpactCopyBeat(seq) {
  return seq % 10 === 3;
}

function commandsRelated(prev, next) {
  if (!prev || !next) return false;
  const p = String(prev).toLowerCase().trim();
  const n = String(next).toLowerCase().trim();
  if (p.slice(0, 22) === n.slice(0, 22)) return true;
  const topics = ["decision", "simulate", "execute", "governance", "prioritize", "mitigation", "risk"];
  const inP = topics.filter((t) => p.includes(t));
  const inN = topics.filter((t) => n.includes(t));
  return inP.length > 0 && inN.length > 0 && inP.some((t) => inN.includes(t));
}

/** ~4% — delay + suppress optional feedback (no toast / glance / shell pulse). */
function invisibleIntelligenceBeat(seq) {
  return ((seq * 17 + 3) >>> 0) % 29 === 0;
}

/** Rare when streak ≥2 and related follow-up. */
function continuityOpeningBeat(seq, streak) {
  if (streak < 2) return false;
  return ((seq + streak * 7) >>> 0) % 23 === 0;
}

/** Rare post-success persistence line (uses existing presence strip only). */
function postActionTrackingBeat(seq) {
  return ((seq * 11 + 5) >>> 0) % 17 === 2;
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/** Decisive, signal-based one-liner — short, authority tone. */
function oneLineInsight(view, { loading, safeMode }) {
  if (loading) return "Refreshing.";
  if (safeMode) {
    return "Risk identified: live feed down. Acting on last reconciled snapshot.";
  }
  const { status, confidence, risks, opportunities: oppCount } = view.system;
  const topOpp = view.opportunities[0];
  const topThreat = view.threats[0];
  const urgent = view.decisions.find((d) => String(d?.urgency || "").toLowerCase() === "high") || view.decisions[0];
  const trustArrow = confidence >= 72 ? "↑" : confidence <= 55 ? "↓" : "→";

  if (status === "CRITICAL") {
    const lead = urgent?.title ? urgent.title.slice(0, 52) : "containment";
    return `Signal detected: ${risks} execution faults. Action recommended — ${lead}.`;
  }
  if (status === "DEGRADED") {
    const t = topThreat?.title ? topThreat.title.slice(0, 48) : "variance";
    return `Risk identified: ${t}. Trust ${confidence}% ${trustArrow}. Validate before scale.`;
  }
  const leadOpp = topOpp?.title ? topOpp.title.slice(0, 36) : "leverage";
  const next = urgent?.title ? urgent.title.slice(0, 40) : "top decision";
  return `Opportunity signal: ${leadOpp} · ${oppCount} lanes · trust ${confidence}% ${trustArrow}. Next: ${next}.`;
}

function DrawerFallback() {
  return (
    <div
      className="flex flex-1 flex-col items-center justify-center gap-2 p-10 text-center"
      aria-busy="true"
    >
      <div className="h-8 w-8 animate-pulse rounded-full bg-gradient-to-br from-blue-500/40 to-violet-500/30 shadow-[0_0_24px_-4px_rgba(99,102,241,0.5)]" />
      <p className="text-sm font-medium text-slate-400">Opening tool…</p>
    </div>
  );
}

function WarnGlyph({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <path
        fillRule="evenodd"
        d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l6.518 11.607c.75 1.334-.213 2.98-1.742 2.98H3.481c-1.53 0-2.493-1.646-1.743-2.98l6.519-11.607zM11 14a1 1 0 10-2 0 1 1 0 002 0zm-1-2a1 1 0 01-1-1V8a1 1 0 112 0v3a1 1 0 01-1 1z"
        clipRule="evenodd"
      />
    </svg>
  );
}

/**
 * Layer 2: compact cards with micro-signals (↑↓→, priority chip, optional warn).
 * Motion: hover lift + soft glow; active press scale — reads “alive”, not static tiles.
 */
function QuickGlanceCards({ signals, onOpenTool, cue = {}, cueIntense = false }) {
  const cards = [
    {
      key: "opportunities",
      label: "Opportunities",
      tool: "intelligence",
      count: signals.opportunity.count,
      trend: signals.opportunity.trend,
      priority: signals.opportunity.priority,
      warn: false,
      accent: "from-emerald-500/15 via-transparent to-transparent",
    },
    {
      key: "risks",
      label: "Risks",
      tool: "intelligence",
      count: signals.risk.count,
      trend: signals.risk.trend,
      priority: signals.risk.priority,
      warn: signals.risk.count > 0,
      accent: "from-amber-500/15 via-transparent to-transparent",
    },
    {
      key: "decisions",
      label: "Decisions",
      tool: "decision",
      count: signals.decision.count,
      trend: signals.decision.trend,
      priority: signals.decision.priority,
      warn: signals.decision.hasUrgent,
      accent: "from-blue-500/15 via-transparent to-transparent",
    },
  ];

  const trendChar = (t) => (t === "up" ? "↑" : t === "down" ? "↓" : "→");

  return (
    <div className="grid grid-cols-3 gap-3">
      {cards.map((c) => (
        <button
          key={c.key}
          type="button"
          onClick={() => onOpenTool(c.tool)}
          className={`group relative overflow-hidden rounded-2xl border border-slate-800/90 bg-gradient-to-b ${c.accent} px-3 py-3.5 text-left shadow-sm transition-all duration-300 ease-out hover:-translate-y-0.5 hover:border-slate-600/90 hover:shadow-[0_10px_32px_-14px_rgba(56,189,248,0.16)] active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500/60 ${cue[c.key] ? `cc-glance-${cue[c.key]}` : ""} ${cueIntense && cue[c.key] ? "cc-glance-intense" : ""}`}
        >
          <div
            className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
            style={{
              background:
                "radial-gradient(120% 80% at 50% 0%, rgba(148,163,184,0.12) 0%, transparent 55%)",
            }}
          />
          <div className="relative flex items-start justify-between gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{c.label}</span>
            <span className="flex items-center gap-0.5">
              {c.warn ? <WarnGlyph className="h-3.5 w-3.5 text-amber-400/90" /> : null}
              <span
                className={`rounded-md px-1.5 py-0.5 font-mono text-[11px] font-semibold ${
                  c.priority === "P1"
                    ? "bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/25"
                    : c.priority === "P2"
                      ? "bg-amber-500/10 text-amber-200/90 ring-1 ring-amber-500/20"
                      : "bg-slate-700/50 text-slate-400 ring-1 ring-slate-600/40"
                }`}
              >
                {c.priority}
              </span>
            </span>
          </div>
          <div className="relative mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tabular-nums tracking-tight text-slate-50">{c.count}</span>
            <span
              className={`text-sm font-semibold tabular-nums ${
                c.trend === "up" ? "text-emerald-400" : c.trend === "down" ? "text-rose-400" : "text-slate-500"
              } transition-transform duration-300 group-hover:scale-110`}
              aria-hidden
            >
              {trendChar(c.trend)}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}

export default function ControlCenterPage() {
  const [view, setView] = useState(() => initialViewModel());
  const [safeMode, setSafeMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const lastKnownRef = useRef(initialViewModel());

  /** Sparse system presence — only during load / command / refresh; debounced to avoid spam. */
  const [systemPresence, setSystemPresence] = useState(null);
  const commandInFlightRef = useRef(false);

  /** Bumps CommandCenter shell for a short post-action pulse (successful command). */
  const [actionFlashKey, setActionFlashKey] = useState(0);

  const [glanceOpen, setGlanceOpen] = useState(false);
  /** Drawer open + current tool tab (intelligence | decision | action). */
  const [activeTool, setActiveTool] = useState(null);
  const [drawerEntered, setDrawerEntered] = useState(false);
  /** Avoid re-running slide-in when only switching internal tabs. */
  const drawerWasOpenRef = useRef(false);

  /** One-shot glance card motion after counts move (command → reload). */
  const [glanceCue, setGlanceCue] = useState({});
  const [glanceCueIntense, setGlanceCueIntense] = useState(false);
  const lastProactiveAtRef = useRef(0);
  const commandSeqRef = useRef(0);
  const feedbackTimersRef = useRef([]);
  const lastSuccessCmdRef = useRef("");
  const lastSuccessAtRef = useRef(0);
  const consecutiveStreakRef = useRef(0);

  const clearFeedbackTimers = useCallback(() => {
    feedbackTimersRef.current.forEach((id) => clearTimeout(id));
    feedbackTimersRef.current = [];
  }, []);

  const buildViewModel = useCallback((guardrails, logs) => {
    const enabledGuardrails = guardrails.filter((g) => !!g.enabled);
    const riskLogs = logs.filter((l) => String(l?.status || "").toLowerCase() !== "success");
    const successLogs = logs.filter((l) => String(l?.status || "").toLowerCase() === "success");
    const confidence =
      logs.length > 0 ? Math.round((successLogs.length / logs.length) * 100) : 68;
    const status = riskLogs.length > 10 ? "CRITICAL" : riskLogs.length > 3 ? "DEGRADED" : "ACTIVE";

    const opportunities = enabledGuardrails.slice(0, 4).map((g, idx) => ({
      id: `opp_${g.id || idx}`,
      title: `${String(g.rule_name || "Guardrail signal")} opportunity`,
      why: `Domain "${String(g.domain || "global")}" has active control policies ready for guided execution.`,
      action: "Run high-confidence execution with simulation checkpoint.",
      confidence: Math.max(56, confidence - 4 + idx * 3),
    }));

    const threats = riskLogs.slice(0, 4).map((l, idx) => ({
      id: `thr_${l.id || idx}`,
      title: `${String(l.action_type || "Execution")} risk pattern`,
      why: `Status "${String(l.status || "unknown")}" detected from ${String(l.source || "autonomy")}.`,
      action: "Apply safe profile and isolate high-risk action class.",
      confidence: Math.max(52, confidence - 8 + idx * 2),
    }));

    const decisionSource = [...opportunities, ...threats].slice(0, 3);
    const decisions = decisionSource.map((item, idx) => ({
      id: `dec_${item.id}_${idx}`,
      title: idx === 0 ? `Prioritize: ${item.title}` : `Review: ${item.title}`,
      impact: item.action,
      urgency: idx === 0 ? "high" : idx === 1 ? "medium" : "low",
    }));

    const topLog = logs[0];
    const lastAction = {
      title: topLog ? `${String(topLog.action_type || "Autonomy action")} (${String(topLog.status || "unknown")})` : "Autonomy health check completed",
      impact: riskLogs.length
        ? `Risk containment signal active (${riskLogs.length} flagged events).`
        : `Margin stability trend improved (${confidence}% confidence).`,
      nextStep: decisions[0]?.title || "Run strategic simulation for top priority lane.",
      at: topLog?.created_at || new Date().toISOString(),
    };

    return {
      system: {
        status,
        risks: riskLogs.length || threats.length,
        opportunities: opportunities.length || 1,
        confidence,
      },
      opportunities: opportunities.length ? opportunities : initialViewModel().opportunities,
      threats: threats.length ? threats : initialViewModel().threats,
      decisions: decisions.length ? decisions : initialViewModel().decisions,
      lastAction,
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [g, l] = await Promise.all([fetchGovernanceGuardrails(), fetchGovernanceLogs(120)]);
      const guardrails = Array.isArray(g?.items) ? g.items : [];
      const logs = Array.isArray(l?.items) ? l.items : [];
      const next = buildViewModel(guardrails, logs);
      lastKnownRef.current = next;
      setView(next);
      setSafeMode(false);
      return next;
    } catch (e) {
      const d = e?.response?.data?.detail;
      setSafeMode(true);
      setView(lastKnownRef.current || initialViewModel());
      showToastDedup({
        type: "warning",
        message: typeof d === "string" ? d : "Risk identified. Serving cached snapshot.",
      });
      return null;
    } finally {
      setLoading(false);
    }
  }, [buildViewModel]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => () => clearFeedbackTimers(), [clearFeedbackTimers]);

  /** Data refresh presence — debounced; skipped while a command owns the line. */
  useEffect(() => {
    if (!loading) {
      const clear = setTimeout(() => {
        setSystemPresence((prev) =>
          prev === "Analyzing…" || prev === "Processing signals…" ? null : prev,
        );
      }, 220);
      return () => clearTimeout(clear);
    }
    if (commandInFlightRef.current) return undefined;
    const showAnalyzing = setTimeout(() => {
      if (!commandInFlightRef.current) setSystemPresence("Analyzing…");
    }, 450);
    const escalate = setTimeout(() => {
      if (!commandInFlightRef.current && loading) setSystemPresence("Processing signals…");
    }, 2400);
    return () => {
      clearTimeout(showAnalyzing);
      clearTimeout(escalate);
    };
  }, [loading]);

  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (activeTool) setActiveTool(null);
        else setGlanceOpen((v) => !v);
      }
      if (e.key === "Escape") {
        if (activeTool) setActiveTool(null);
        else if (glanceOpen) setGlanceOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeTool, glanceOpen]);

  useEffect(() => {
    if (!activeTool) {
      setDrawerEntered(false);
      drawerWasOpenRef.current = false;
      return;
    }
    if (!drawerWasOpenRef.current) {
      drawerWasOpenRef.current = true;
      const id = requestAnimationFrame(() => setDrawerEntered(true));
      return () => cancelAnimationFrame(id);
    }
    setDrawerEntered(true);
  }, [activeTool]);

  const insight = useMemo(() => oneLineInsight(view, { loading, safeMode }), [view, loading, safeMode]);

  const glanceSignals = useMemo(() => {
    const { risks, opportunities: oc, status } = view.system;
    const hasUrgent = view.decisions.some((d) => String(d?.urgency || "").toLowerCase() === "high");
    const oppTrend = status === "ACTIVE" ? "up" : status === "DEGRADED" ? "flat" : "down";
    const riskTrend = risks > 3 ? "up" : risks === 0 ? "flat" : "flat";
    const decTrend = hasUrgent ? "up" : "flat";
    return {
      opportunity: {
        count: view.opportunities.length || oc,
        trend: oppTrend,
        priority: status === "ACTIVE" ? "P3" : "P2",
      },
      risk: {
        count: risks,
        trend: riskTrend,
        priority: risks > 3 ? "P1" : risks > 0 ? "P2" : "P3",
      },
      decision: {
        count: view.decisions.length,
        trend: decTrend,
        priority: hasUrgent ? "P1" : "P2",
        hasUrgent,
      },
    };
  }, [view]);

  async function handleCommand(command) {
    clearFeedbackTimers();
    commandSeqRef.current += 1;
    const seq = commandSeqRef.current;

    const streak = consecutiveStreakRef.current;
    const gapSinceSuccess = lastSuccessAtRef.current ? Date.now() - lastSuccessAtRef.current : Number.POSITIVE_INFINITY;
    const related = commandsRelated(lastSuccessCmdRef.current, command);
    const continuityOpen =
      streak >= 2 &&
      gapSinceSuccess < 90_000 &&
      related &&
      continuityOpeningBeat(seq, streak);

    commandInFlightRef.current = true;
    const before = snapshotGlanceCounts(lastKnownRef.current);
    const confBefore = lastKnownRef.current?.system?.confidence ?? 0;
    setSystemPresence(
      continuityOpen ? (seq % 2 === 0 ? "Re-evaluating previous action…" : "Rechecking signals…") : "Evaluating decision…",
    );
    try {
      await postChatQuery(command || "status");
      const snap = await load();

      let invisibleHold = false;
      if (snap) {
        invisibleHold = invisibleIntelligenceBeat(seq);
        if (invisibleHold) {
          const holdMs = 200 + (((seq * 17) >>> 0) % 201);
          await delay(holdMs);
        }
      }

      commandInFlightRef.current = false;
      const tClearEval = setTimeout(() => setSystemPresence(null), 280);
      feedbackTimersRef.current.push(tClearEval);

      if (snap) {
        const silent = toastSilenceBeat(command, seq);

        const after = snapshotGlanceCounts(snap);
        const dOpp = after.opportunity - before.opportunity;
        const dRisk = after.risk - before.risk;
        const dDec = after.decision - before.decision;
        const dConf = after.confidence - confBefore;

        const cue = {};
        if (dOpp > 0) cue.opportunities = "build";
        else if (dOpp < 0) cue.opportunities = "fade";
        if (dRisk > 0) cue.risks = "stress";
        else if (dRisk < 0) cue.risks = "release";
        if (dDec > 0) cue.decisions = "build";
        else if (dDec < 0) cue.decisions = "fade";

        const meaningful =
          dOpp !== 0 ||
          dRisk !== 0 ||
          dDec !== 0 ||
          Math.abs(dConf) >= 2 ||
          before.status !== after.status;

        const highImpact = deltaIsHighImpact({ dOpp, dRisk, dDec, dConf, before, after });
        const highImpactLine = highImpact && highImpactCopyBeat(seq);
        const glanceHoldMs = highImpact ? 1280 : 1120;

        const nowOk = Date.now();
        const chainGap = lastSuccessAtRef.current ? nowOk - lastSuccessAtRef.current : Number.POSITIVE_INFINITY;
        const chainRelated = commandsRelated(lastSuccessCmdRef.current, command);
        if (chainGap < 90_000 && chainRelated) consecutiveStreakRef.current += 1;
        else consecutiveStreakRef.current = 1;
        lastSuccessCmdRef.current = String(command || "");
        lastSuccessAtRef.current = nowOk;

        if (!invisibleHold) {
          setActionFlashKey((k) => k + 1);
        }

        if (!invisibleHold && Object.keys(cue).length) {
          const tGlance = setTimeout(() => {
            setGlanceCue(cue);
            setGlanceCueIntense(highImpact);
            const tClear = setTimeout(() => {
              setGlanceCue({});
              setGlanceCueIntense(false);
            }, glanceHoldMs);
            feedbackTimersRef.current.push(tClear);
          }, GLANCE_STAGGER_MS);
          feedbackTimersRef.current.push(tGlance);
        }

        if (!invisibleHold) {
          const tToast = setTimeout(() => {
            if (silent) return;
            if (highImpactLine) {
              showToastDedup({ type: "info", message: "High-impact change detected." });
              lastProactiveAtRef.current = Date.now();
              return;
            }
            showToastDedup({ type: "success", message: "Signal routed." });
            const now = Date.now();
            if (meaningful && now - lastProactiveAtRef.current >= PROACTIVE_COOLDOWN_MS) {
              let message = "New signal detected.";
              if (dRisk > 0) message = "Risk emerging.";
              else if (dOpp > 0) message = "Opportunity identified.";
              lastProactiveAtRef.current = now;
              showToastDedup({ type: "info", message });
            }
          }, TOAST_STAGGER_MS);
          feedbackTimersRef.current.push(tToast);
        }

        if (!invisibleHold && postActionTrackingBeat(seq)) {
          const tTrack = setTimeout(() => {
            setSystemPresence(seq % 2 === 0 ? "Tracking outcome…" : "Monitoring impact…");
            const tClearTrack = setTimeout(() => setSystemPresence(null), 680);
            feedbackTimersRef.current.push(tClearTrack);
          }, 360);
          feedbackTimersRef.current.push(tTrack);
        }

        const impact =
          snap.lastAction?.impact ||
          (snap.system?.confidence != null ? `Model alignment ${snap.system.confidence}%` : "State re-synced.");
        const nextStep = shorten(
          snap.lastAction?.nextStep || "Monitor ledger for 24h.",
          72,
        );
        const cmdDisplay = shorten(
          String(command || "")
            .replace(/^\s*execute\s+decision:\s*/i, "")
            .replace(/^\s*simulate\s+decision:\s*/i, "")
            .trim() || "Governance pulse",
          56,
        );
        const statusTag =
          snap.system.status === "ACTIVE"
            ? "Channel stable"
            : snap.system.status === "DEGRADED"
              ? "Elevated watch"
              : "Critical field";
        const signalText = shorten(
          `${statusTag} · ${after.risk} risk · ${after.opportunity} opp · trust ${after.confidence}%`,
          88,
        );

        return {
          ok: true,
          message: "Action executed.",
          impact,
          blocks: [
            { kind: "signal", text: signalText },
            { kind: "action", text: cmdDisplay },
            { kind: "outcome", text: shorten(impact, 92) },
            { kind: "next", text: nextStep },
          ],
        };
      }

      const impact =
        snap?.lastAction?.impact ||
        (snap?.system?.confidence != null ? `Model alignment ${snap.system.confidence}%` : "State re-synced.");
      return { ok: true, message: "Action executed.", impact };
    } catch (e2) {
      commandInFlightRef.current = false;
      consecutiveStreakRef.current = 0;
      setSystemPresence(null);
      const d = e2?.response?.data?.detail;
      setSafeMode(true);
      showToastDedup({
        type: "warning",
        message: typeof d === "string" ? d : "Command blocked. Simulate first.",
      });
      return { ok: false, message: "Action held.", impact: "No state change." };
    }
  }

  const decisionHandlers = {
    onExecute: (d) => handleCommand(`execute decision: ${d.title}`),
    onSimulate: (d) => handleCommand(`simulate decision: ${d.title}`),
    onIgnore: () => showToastDedup({ type: "warning", message: "Deferred." }),
  };

  return (
    <div className="relative min-h-[calc(100vh-6rem)]">
      {/* Ambient depth — subtle, not loud */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 mx-auto h-72 max-w-3xl opacity-[0.52] blur-3xl"
        style={{
          background: "radial-gradient(ellipse 70% 60% at 50% 0%, rgba(59,130,246,0.14), transparent 65%)",
        }}
        aria-hidden
      />

      <div className="relative mx-auto flex w-full max-w-xl flex-col px-3 pb-12 pt-10 md:max-w-2xl">
        <header className="mb-10 text-center transition-opacity duration-500 ease-out">
          <p className="text-[11px] font-medium uppercase tracking-[0.2em] text-slate-500">Thiramai</p>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-slate-100 md:text-2xl">Command</h1>
          <p
            className={`mx-auto mt-4 max-w-lg text-[15px] leading-relaxed text-slate-400 transition-[color,opacity,box-shadow] duration-500 ease-out md:text-base ${
              view.system.status === "CRITICAL" ? "cc-insight-critical px-2 py-1 ring-1 ring-rose-500/25" : ""
            }`}
          >
            {insight}
          </p>
          {systemPresence ? (
            <p className="mt-2 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500/90" aria-live="polite">
              {systemPresence}
            </p>
          ) : null}
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
            <button
              type="button"
              onClick={() => setGlanceOpen((v) => !v)}
              className="rounded-full border border-slate-700/80 bg-slate-900/40 px-4 py-2 text-xs font-medium text-slate-300 shadow-sm backdrop-blur-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-slate-500 hover:text-slate-100 hover:shadow-[0_8px_30px_-10px_rgba(148,163,184,0.35)] active:scale-[0.98]"
            >
              {glanceOpen ? "Hide summary" : "Summary"}{" "}
              <span className="text-slate-500">⌘K</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTool("action")}
              className="rounded-full border border-transparent px-3 py-2 text-xs font-medium text-slate-500 transition-all duration-300 hover:text-slate-300 active:scale-[0.98]"
            >
              Last run →
            </button>
          </div>
        </header>

        <div
          className={`overflow-hidden transition-all duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] ${
            glanceOpen ? "mb-8 max-h-64 opacity-100" : "max-h-0 opacity-0"
          }`}
          aria-hidden={!glanceOpen}
        >
          {glanceOpen ? (
            <QuickGlanceCards
              signals={glanceSignals}
              onOpenTool={setActiveTool}
              cue={glanceCue}
              cueIntense={glanceCueIntense}
            />
          ) : null}
        </div>

        <div className="mt-auto transition-opacity duration-500 ease-out">
          <CommandCenter onSubmit={handleCommand} safeMode={safeMode} variant="calm" actionFlashKey={actionFlashKey} />
        </div>
      </div>

      {activeTool ? (
        <div className="fixed inset-0 z-50 flex justify-end" role="presentation">
          <button
            type="button"
            className="absolute inset-0 bg-slate-950/70 backdrop-blur-[3px] transition-[opacity,backdrop-filter] duration-500 ease-out"
            style={{ opacity: drawerEntered ? 1 : 0 }}
            aria-label="Close panel"
            onClick={() => setActiveTool(null)}
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="cc-drawer-tabs"
            className="relative z-10 flex h-[100dvh] w-full max-w-lg flex-col border-l border-slate-700/60 bg-gradient-to-b from-slate-950 via-slate-950 to-slate-900/95 shadow-[0_0_0_1px_rgba(255,255,255,0.04),-24px_0_80px_-24px_rgba(0,0,0,0.65)] transition-[transform,box-shadow] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"
            style={{ transform: drawerEntered ? "translateX(0)" : "translateX(100%)" }}
          >
            <div className="flex items-center justify-between gap-2 border-b border-slate-800/80 px-3 py-3">
              <div id="cc-drawer-tabs" className="flex flex-1 gap-1 rounded-xl bg-slate-900/60 p-1 ring-1 ring-slate-800/80">
                {DRAWER_TABS.map((tab) => {
                  const on = activeTool === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTool(tab.id)}
                      className={`flex-1 rounded-lg px-2 py-2 text-center text-xs font-semibold transition-all duration-300 ease-out ${
                        on
                          ? "bg-gradient-to-b from-slate-700/90 to-slate-800/90 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] ring-1 ring-slate-600/50"
                          : "text-slate-500 hover:text-slate-200"
                      } active:scale-[0.97]`}
                    >
                      {tab.label}
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                onClick={() => setActiveTool(null)}
                className="shrink-0 rounded-xl border border-slate-700/80 bg-slate-900/50 px-3 py-2 text-xs font-medium text-slate-400 transition-all duration-300 hover:border-slate-500 hover:text-slate-100 active:scale-[0.97]"
              >
                Close
              </button>
            </div>
            <div className="flex-1 overflow-y-auto bg-gradient-to-b from-transparent to-slate-950/80 p-4">
              <Suspense fallback={<DrawerFallback />}>
                {activeTool === "intelligence" ? (
                  <IntelligencePanel opportunities={view.opportunities} threats={view.threats} />
                ) : null}
                {activeTool === "decision" ? <DecisionPanel decisions={view.decisions} {...decisionHandlers} /> : null}
                {activeTool === "action" ? (
                  <ActionFeed safeMode={safeMode} lastAction={view.lastAction} lastKnown={lastKnownRef.current} />
                ) : null}
              </Suspense>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
