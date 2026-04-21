import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  createInviteLink,
  fetchPersonalTodayBrief,
  fetchProductBootstrap,
  fetchWowInsights,
  postProductOnboarding,
} from "../api/commandCenterApi.js";
import { requestNotificationPermission, useSmartNotifications } from "../hooks/useSmartNotifications.js";
import { registerWebPushSubscription } from "../lib/webPushSubscribe.js";
import { showToastDedup } from "../lib/toastDedup.js";
import { safeArray } from "../lib/safeData.js";

function formatLongDate(isoDate) {
  if (!isoDate) return "";
  try {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    }).format(new Date(`${isoDate}T12:00:00`));
  } catch {
    return isoDate;
  }
}

function formatTime(d) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(d);
}

function weatherLabel(w) {
  if (!w || w.temperature_c == null) return null;
  const t = typeof w.temperature_c === "number" ? Math.round(w.temperature_c) : w.temperature_c;
  return `${t}°C`;
}

function saluteForHour(h) {
  if (h >= 5 && h < 12) return "Good morning";
  if (h >= 12 && h < 17) return "Good afternoon";
  if (h >= 17 && h < 21) return "Good evening";
  return "Good night";
}

function routeFromActionUrl(u) {
  if (!u) return "/today";
  const s = String(u).replace(/^#\//, "/").replace(/^#/, "/");
  return s.startsWith("/") ? s : `/today`;
}

function winStorageKey(isoDate) {
  return `thiramai_win_of_day_${isoDate || "today"}`;
}

function TodayPageSkeleton() {
  return (
    <div className="cc-today-page cc-today-page--skeleton" aria-busy="true" aria-label="Loading Today">
      <div className="cc-today-skeleton-block cc-today-skeleton-hero" />
      <div className="cc-today-skeleton-block cc-today-skeleton-card" />
      <div className="cc-today-skeleton-block cc-today-skeleton-card cc-today-skeleton-card--short" />
    </div>
  );
}

export default function TodayPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(() => new Date());
  const [notifOn, setNotifOn] = useState(
    () => typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted",
  );
  const [winText, setWinText] = useState("");
  const [pushBusy, setPushBusy] = useState(false);
  const [wowOpen, setWowOpen] = useState(false);
  const [wowInsights, setWowInsights] = useState([]);
  const [wowCaptain, setWowCaptain] = useState("");
  const [wowBusy, setWowBusy] = useState(false);
  const [shareBusy, setShareBusy] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(true);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const mq = window.matchMedia("(min-width: 900px)");
    const apply = () => setScheduleOpen(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchPersonalTodayBrief(null);
      setData(payload);
    } catch (err) {
      const d = err?.response?.data?.detail;
      setError(typeof d === "string" ? d : err?.message || "Could not load Today");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const boot = await fetchProductBootstrap();
        if (cancelled || !boot?.hints?.wow_pending) return;
        const w = await fetchWowInsights();
        if (cancelled || !w?.insights?.length) return;
        setWowInsights(w.insights.slice(0, 3));
        setWowCaptain(typeof w.captain_message === "string" ? w.captain_message : "");
        setWowOpen(true);
      } catch {
        /* non-fatal */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);

  const isoDate = data?.date || "";
  useEffect(() => {
    if (!isoDate || typeof window === "undefined") return;
    setWinText(window.localStorage.getItem(winStorageKey(isoDate)) || "");
  }, [isoDate]);

  useSmartNotifications(data, { enabled: notifOn });

  const tp = data?.tasks_progress;
  const doneProgress = Number(tp?.completed_today) || 0;
  const openProgress = Number(tp?.open_total) || 0;
  const totalProgress = doneProgress + openProgress;
  const progressPct =
    totalProgress <= 0 ? null : Math.min(100, Math.round((doneProgress / totalProgress) * 100));

  const persistWin = useCallback(() => {
    if (!isoDate || typeof window === "undefined") return;
    window.localStorage.setItem(winStorageKey(isoDate), winText.trim());
  }, [isoDate, winText]);

  const greeting = data?.greeting?.display_name || "there";
  const hour = now.getHours();
  const salute = saluteForHour(hour);

  const weather = data?.weather;
  const weatherLine = data?.weather_configured ? weatherLabel(weather) : null;
  const focus = data?.focus_task;
  const dueField = focus?.due_date || focus?.deadline;
  const meetings = safeArray(data?.meetings_today);
  const nextMeeting = data?.next_meeting;
  const health = data?.health_score_yesterday || data?.health_score;
  const biz = data?.business_snapshot;
  const alerts = safeArray(data?.proactive_alerts);
  const insight = data?.motivational_insight || data?.ai_insight || "";
  const streak = data?.habit_streak_days;
  const lowStock = data?.low_stock_count;
  const upcomingEmi = data?.upcoming_emis;
  const cross = data?.cross_domain_insights;

  async function onEnableNotifs() {
    const p = await requestNotificationPermission();
    setNotifOn(p === "granted");
  }

  const pushSupported =
    typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window;

  async function onDismissWow() {
    setWowBusy(true);
    try {
      await postProductOnboarding({ wow_ack: true });
      setWowOpen(false);
    } catch (err) {
      const d = err?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Could not save" });
    } finally {
      setWowBusy(false);
    }
  }

  async function onShareThiramai() {
    setShareBusy(true);
    try {
      const r = await createInviteLink();
      const path = r?.share_url || (r?.code ? `/signup?ref=${encodeURIComponent(r.code)}` : "");
      if (!path) throw new Error("No invite link");
      const url = `${window.location.origin}${path.startsWith("/") ? path : `/${path}`}`;
      await navigator.clipboard.writeText(url);
      showToastDedup({ type: "success", message: "Invite link copied — share with a teammate" });
    } catch (err) {
      const d = err?.response?.data?.detail;
      showToastDedup({
        type: "error",
        message: typeof d === "string" ? d : err?.message || "Could not create invite",
      });
    } finally {
      setShareBusy(false);
    }
  }

  async function onBackgroundPush() {
    if (!pushSupported) {
      showToastDedup({ type: "warning", message: "Web Push not supported in this browser" });
      return;
    }
    if (!import.meta.env.PROD) {
      showToastDedup({
        type: "info",
        message: "Use a production build over HTTPS (or localhost) so the service worker is registered.",
      });
    }
    setPushBusy(true);
    try {
      await registerWebPushSubscription();
      showToastDedup({
        type: "success",
        message: "Background push enabled — meeting, EMI, and daily brief alerts when the app is closed.",
      });
    } catch (err) {
      const d = err?.response?.data?.detail;
      const msg = typeof d === "string" ? d : err?.message || "Push setup failed";
      showToastDedup({ type: "error", message: msg });
    } finally {
      setPushBusy(false);
    }
  }

  const wowLayer =
    wowOpen ? (
      <div className="cc-wow-overlay" role="dialog" aria-modal="true" aria-labelledby="cc-wow-title">
        <div className="cc-wow-modal cc-card">
          <h2 id="cc-wow-title" className="cc-wow-modal-title">
            Your first three insights
          </h2>
          <p className="cc-muted" style={{ marginTop: 0 }}>
            Pulled from your workspace and personal OS — add data anytime to sharpen these.
          </p>
          {wowCaptain ? <p className="cc-wow-captain">{wowCaptain}</p> : null}
          <ol className="cc-wow-list">
            {safeArray(wowInsights).map((row, i) => (
              <li key={i} className="cc-wow-item">
                <strong>{row.title || "Insight"}</strong>
                {row.detail ? <p className="cc-muted cc-wow-detail">{row.detail}</p> : null}
              </li>
            ))}
          </ol>
          <div className="cc-wow-actions">
            <button type="button" className="cc-btn cc-btn-primary" disabled={wowBusy} onClick={onDismissWow}>
              {wowBusy ? "Saving…" : "Continue to Today"}
            </button>
          </div>
        </div>
      </div>
    ) : null;

  if (loading && !data) {
    return (
      <>
        {wowLayer}
        <TodayPageSkeleton />
      </>
    );
  }

  if (error && !data) {
    return (
      <>
        {wowLayer}
        <div className="cc-today-page">
          <p className="cc-error">{error}</p>
          <button type="button" className="cc-btn cc-btn-primary" onClick={load}>
            Retry
          </button>
        </div>
      </>
    );
  }

  return (
    <div className="cc-today-page">
      {wowLayer}
      <header className="cc-today-hero">
        <div>
          <h1 className="cc-today-greeting">
            {salute}, {greeting}
          </h1>
          <p className="cc-today-sub">
            <span className="cc-today-date">
              {data?.day_of_week ? `${data.day_of_week} · ` : ""}
              {formatLongDate(data?.date)}
            </span>
            <span className="cc-today-time" aria-hidden="true">
              {" · "}
              {formatTime(now)}
            </span>
            {weatherLine ? (
              <span className="cc-today-weather">
                {" · "}
                {weatherLine}
              </span>
            ) : data?.weather_configured === false ? (
              <span className="cc-muted cc-today-weather-hint">
                {" · "}
                <span title="Set PERSONAL_OS_WEATHER_LAT / LON on the server for weather">Weather not configured</span>
              </span>
            ) : null}
          </p>
          <div className="cc-today-hero-actions cc-today-hero-actions--primary">
            <button
              type="button"
              className="cc-btn cc-btn-secondary cc-today-notif-btn"
              disabled={shareBusy}
              onClick={onShareThiramai}
              title="Copies signup link with your referral code"
            >
              {shareBusy ? "Preparing…" : "Invite someone"}
            </button>
            <button type="button" className="cc-btn cc-btn-primary cc-today-notif-btn" onClick={load} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          <details className="cc-today-inline-details">
            <summary className="cc-today-inline-summary">Notifications &amp; push</summary>
            <div className="cc-today-inline-details-body">
              <button type="button" className="cc-btn cc-btn-secondary cc-today-notif-btn" onClick={onEnableNotifs}>
                {notifOn ? "In-app reminders on" : "Turn on in-app reminders"}
              </button>
              <button
                type="button"
                className="cc-btn cc-btn-secondary cc-today-notif-btn"
                disabled={!pushSupported || pushBusy}
                onClick={onBackgroundPush}
                title="HTTPS or localhost; VAPID on server"
              >
                {pushBusy ? "Enabling…" : "Background push when app is closed"}
              </button>
            </div>
          </details>
        </div>
      </header>

      {cross?.ok && (cross.captain_message || (cross.top_insights || []).length > 0) ? (
        <section className="cc-card cc-today-priority" aria-label="Captain briefing and top insights">
          <h2 className="cc-today-card-title">Briefing</h2>
          {cross.captain_message ? (
            <p className="cc-today-captain" role="status">
              {cross.captain_message}
            </p>
          ) : null}
          {(cross.top_insights || []).length > 0 ? (
            <ol className="cc-today-top-insights">
              {(cross.top_insights || []).slice(0, 3).map((x) => (
                <li key={x.id || x.title}>
                  <strong>{x.title}</strong>
                  {x.detail ? <span className="cc-muted"> — {x.detail}</span> : null}
                </li>
              ))}
            </ol>
          ) : null}
        </section>
      ) : null}

      <section className="cc-card cc-today-actions-card" aria-label="Next actions">
        <h2 className="cc-today-card-title">Next actions</h2>
        {nextMeeting ? (
          <div className="cc-today-action-row">
            <span className="cc-muted">Next</span>
            <strong className="cc-today-action-title">{nextMeeting.title}</strong>
            <span className="cc-muted">
              {nextMeeting.countdown_text ||
                (nextMeeting.scheduled_at ? formatTime(new Date(nextMeeting.scheduled_at)) : "—")}
            </span>
          </div>
        ) : (
          <p className="cc-muted" style={{ marginTop: 0 }}>
            No meeting coming up — use the schedule below when you need detail.
          </p>
        )}
        {focus ? (
          <div className="cc-today-action-row">
            <Link className="cc-btn cc-btn-primary cc-today-link-btn" to="/personal/productivity">
              Focus: {focus.title}
            </Link>
          </div>
        ) : (
          <Link className="cc-btn cc-btn-secondary cc-today-link-btn" to="/personal/productivity">
            Add a focus mission
          </Link>
        )}
      </section>

      <details
        className="cc-today-schedule-details"
        open={scheduleOpen}
        onToggle={(e) => setScheduleOpen(e.target.open)}
      >
        <summary className="cc-today-schedule-summary">Schedule, business &amp; personal data</summary>
        <div className="cc-today-grid">
      {progressPct != null && (
        <section className="cc-card cc-today-progress" aria-label="Task progress today">
          <div className="cc-today-progress-head">
            <span className="cc-today-card-title" style={{ margin: 0 }}>
              Today&apos;s momentum
            </span>
            {streak != null && streak > 0 ? (
              <span className="cc-today-streak" title="Best active habit streak">
                🔥 {streak}d streak
              </span>
            ) : null}
          </div>
          <div className="cc-today-progress-bar-wrap">
            <div className="cc-today-progress-bar" style={{ width: `${progressPct}%` }} />
          </div>
          <p className="cc-muted" style={{ fontSize: 13, marginTop: 8 }}>
            {tp?.completed_today ?? 0} completed · {tp?.open_total ?? 0} open missions
          </p>
        </section>
      )}

        {cross?.ok && ((cross.risk_alerts || []).length > 0 || (cross.recommendations || []).length > 0) ? (
          <section className="cc-card cc-today-cross-domain cc-today-cross-domain--extra" aria-label="Risks and recommendations">
            <h2 className="cc-today-card-title">More intelligence</h2>
            {(cross.risk_alerts || []).length > 0 ? (
              <div className="cc-today-cross-risks">
                <p className="cc-today-cross-sub">Risk alerts</p>
                <ul className="cc-today-cross-list cc-today-cross-list--risks">
                  {(cross.risk_alerts || []).map((line, i) => (
                    <li key={`r-${i}`}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {(cross.recommendations || []).length > 0 ? (
              <div className="cc-today-cross-recs">
                <p className="cc-today-cross-sub">Recommendations</p>
                <ul className="cc-today-cross-list">
                  {(cross.recommendations || []).map((line, i) => (
                    <li key={`c-${i}`}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
        ) : null}

        {focus && dueField ? (
          <section className="cc-card cc-today-focus-due" aria-label="Focus due date">
            <h2 className="cc-today-card-title">Focus due</h2>
            <p className="cc-muted" style={{ fontSize: 13, marginTop: 0 }}>
              {focus.title} — due{" "}
              {new Date(dueField).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
            </p>
          </section>
        ) : null}

        <section className="cc-card cc-today-meetings">
          <h2 className="cc-today-card-title">Today&apos;s meetings</h2>
          {meetings.length === 0 ? (
            <p className="cc-muted">Nothing scheduled today.</p>
          ) : (
            <ul className="cc-today-meeting-list">
              {meetings.map((m) => (
                <li
                  key={m.id}
                  className={`cc-today-meeting-item${m.is_next ? " cc-today-meeting-item--next" : ""}`}
                >
                  <div>
                    <strong>{m.title}</strong>
                    {m.is_next && (
                      <span className="cc-today-badge" title="Next up">
                        Next
                      </span>
                    )}
                  </div>
                  <div className="cc-muted" style={{ fontSize: 13 }}>
                    {m.scheduled_at
                      ? new Date(m.scheduled_at).toLocaleString(undefined, {
                          hour: "numeric",
                          minute: "2-digit",
                        })
                      : "—"}
                    {m.type || m.meeting_type ? ` · ${m.type || m.meeting_type}` : ""}
                  </div>
                  {m.location ? (
                    <div className="cc-muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {m.location}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          <Link className="cc-link-inline" to="/personal">
            Manage in Personal brief
          </Link>
        </section>

        <section className="cc-card cc-today-health">
          <h2 className="cc-today-card-title">Health (yesterday)</h2>
          {health?.score != null ? (
            <>
              <p className="cc-today-health-score">{health.score}</p>
              <p className="cc-muted" style={{ fontSize: 13 }}>
                {health.hint || "Snapshot from your latest log."}
              </p>
            </>
          ) : (
            <p className="cc-muted">{health?.hint || "Log sleep or vitals to see a score."}</p>
          )}
          <Link className="cc-link-inline" to="/personal/health">
            Log health
          </Link>
        </section>

        <section className="cc-card cc-today-business">
          <h2 className="cc-today-card-title">Business snapshot</h2>
          {biz?.ok ? (
            <dl className="cc-today-dl">
              <div>
                <dt>Revenue today</dt>
                <dd>₹{biz.revenue_today_inr ?? "—"}</dd>
              </div>
              <div>
                <dt>This week</dt>
                <dd>₹{biz.revenue_week_inr ?? "—"}</dd>
              </div>
              {(biz.pending_invoices_count ?? 0) > 0 && (
                <div>
                  <dt>Pending invoices</dt>
                  <dd>
                    {biz.pending_invoices_count} · ₹{biz.pending_invoices_total_inr ?? "—"}
                  </dd>
                </div>
              )}
            </dl>
          ) : (
            <p className="cc-muted">No org revenue data, or you&apos;re in personal-only mode.</p>
          )}
          {(biz?.pending_invoices_count ?? 0) > 0 && !biz?.ok ? (
            <p className="cc-muted" style={{ fontSize: 13 }}>
              {biz.pending_invoices_count} unpaid invoice(s) · ₹{biz.pending_invoices_total_inr ?? "—"}
            </p>
          ) : null}
          <Link className="cc-link-inline" to="/dashboard">
            Open business dashboard
          </Link>
        </section>

        {(lowStock ?? 0) > 0 && (
          <section className="cc-card cc-today-stock">
            <h2 className="cc-today-card-title">Inventory</h2>
            <p style={{ fontSize: 18, fontWeight: 700 }}>{lowStock} SKU(s) below threshold</p>
            <Link className="cc-link-inline" to="/dashboard/inventory">
              Review stock
            </Link>
          </section>
        )}

        {upcomingEmi && (
          <section className="cc-card cc-today-emi">
            <h2 className="cc-today-card-title">Next EMI</h2>
            <p style={{ fontWeight: 600 }}>{upcomingEmi.name || "Loan"}</p>
            <p className="cc-muted" style={{ fontSize: 13 }}>
              Due {upcomingEmi.due ? new Date(`${upcomingEmi.due}T12:00:00`).toLocaleDateString() : "—"}
              {upcomingEmi.emi ? ` · ₹${upcomingEmi.emi}` : ""}
            </p>
            <Link className="cc-link-inline" to="/personal/finance">
              Open finance
            </Link>
          </section>
        )}

        <section className="cc-card cc-today-alerts">
          <h2 className="cc-today-card-title">Heads-up</h2>
          {alerts.length === 0 ? (
            <p className="cc-muted">You&apos;re clear — no urgent nudges right now.</p>
          ) : (
            <ul className="cc-today-alert-list">
              {alerts.map((a, i) => (
                <li key={`${a.code}-${i}`} className={`cc-today-alert cc-today-alert--${a.severity || "medium"}`}>
                  <span>{a.message}</span>
                  <span style={{ display: "inline-flex", gap: 10, flexWrap: "wrap" }}>
                    {a.action_url ? (
                      <Link className="cc-today-alert-link" to={routeFromActionUrl(a.action_url)}>
                        Open
                      </Link>
                    ) : null}
                    {a.jarvis_action?.prefill ? (
                      <button
                        type="button"
                        className="cc-today-alert-link"
                        style={{
                          background: "none",
                          border: "none",
                          padding: 0,
                          cursor: "pointer",
                          font: "inherit",
                          textDecoration: "underline",
                        }}
                        onClick={() =>
                          navigate("/dashboard", {
                            state: {
                              jarvisPrefill: String(a.jarvis_action.prefill),
                              jarvisAgent: !!a.jarvis_action.agent_mode,
                            },
                          })
                        }
                      >
                        Jarvis
                      </button>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="cc-card cc-today-insight">
          <h2 className="cc-today-card-title">Insight</h2>
          <p className="cc-today-insight-text">{insight || "Stay consistent today — small steps compound."}</p>
        </section>

        <section className="cc-card cc-today-win">
          <h2 className="cc-today-card-title">Win of the day</h2>
          <p className="cc-muted" style={{ fontSize: 13, marginTop: 0 }}>
            Evening reflection — what went well?
          </p>
          <textarea
            className="cc-textarea cc-today-win-input"
            rows={3}
            placeholder="One thing you’re proud of today…"
            value={winText}
            onChange={(e) => setWinText(e.target.value)}
            onBlur={persistWin}
          />
        </section>
        </div>
      </details>
    </div>
  );
}
