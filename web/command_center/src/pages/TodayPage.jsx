import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { fetchPersonalTodayBrief } from "../api/commandCenterApi.js";
import { requestNotificationPermission, useSmartNotifications } from "../hooks/useSmartNotifications.js";

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

export default function TodayPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(() => new Date());
  const [notifOn, setNotifOn] = useState(
    () => typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted",
  );
  const [winText, setWinText] = useState("");

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
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);

  const isoDate = data?.date || "";
  useEffect(() => {
    if (!isoDate || typeof window === "undefined") return;
    setWinText(window.localStorage.getItem(winStorageKey(isoDate)) || "");
  }, [isoDate]);

  useSmartNotifications(data, { enabled: notifOn });

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
  const meetings = data?.meetings_today || [];
  const nextMeeting = data?.next_meeting;
  const health = data?.health_score_yesterday || data?.health_score;
  const biz = data?.business_snapshot;
  const alerts = data?.proactive_alerts || [];
  const insight = data?.motivational_insight || data?.ai_insight || "";
  const tp = data?.tasks_progress;
  const streak = data?.habit_streak_days;
  const lowStock = data?.low_stock_count;
  const upcomingEmi = data?.upcoming_emis;

  const progressPct = useMemo(() => {
    const done = Number(tp?.completed_today) || 0;
    const open = Number(tp?.open_total) || 0;
    const total = done + open;
    if (total <= 0) return null;
    return Math.min(100, Math.round((done / total) * 100));
  }, [tp]);

  async function onEnableNotifs() {
    const p = await requestNotificationPermission();
    setNotifOn(p === "granted");
  }

  if (loading && !data) {
    return (
      <div className="cc-today-page cc-today-page--loading">
        <div className="cc-today-loading" aria-busy="true">
          <span className="cc-spinner" />
          <p className="cc-muted">Loading your day…</p>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="cc-today-page">
        <p className="cc-error">{error}</p>
        <button type="button" className="cc-btn cc-btn-primary" onClick={load}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="cc-today-page">
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
          <div className="cc-today-hero-actions">
            <button type="button" className="cc-btn cc-btn-secondary cc-today-notif-btn" onClick={onEnableNotifs}>
              {notifOn ? "Reminders on" : "Enable reminders"}
            </button>
          </div>
        </div>
        <button type="button" className="cc-btn" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

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

      {nextMeeting && (
        <section className="cc-card cc-today-next-up" aria-label="Next meeting">
          <h2 className="cc-today-card-title">Next up</h2>
          <p className="cc-today-next-title">{nextMeeting.title}</p>
          <p className="cc-today-next-countdown">
            {nextMeeting.countdown_text
              ? nextMeeting.countdown_text
              : nextMeeting.scheduled_at
                ? formatTime(new Date(nextMeeting.scheduled_at))
                : "—"}
          </p>
          <p className="cc-muted" style={{ fontSize: 13 }}>
            {nextMeeting.scheduled_at
              ? new Date(nextMeeting.scheduled_at).toLocaleString(undefined, {
                  weekday: "short",
                  hour: "numeric",
                  minute: "2-digit",
                })
              : ""}
            {nextMeeting.location ? ` · ${nextMeeting.location}` : ""}
          </p>
        </section>
      )}

      <div className="cc-today-grid">
        <section className="cc-card cc-today-focus">
          <h2 className="cc-today-card-title">Your focus</h2>
          {focus ? (
            <>
              <p className="cc-today-focus-priority">{focus.priority || "P2"}</p>
              <p className="cc-today-focus-title">{focus.title}</p>
              {dueField && (
                <p className="cc-muted" style={{ fontSize: 13, marginTop: 8 }}>
                  Due {new Date(dueField).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                </p>
              )}
              <Link className="cc-btn cc-btn-primary cc-today-link-btn" to="/personal/productivity">
                Open missions
              </Link>
            </>
          ) : (
            <>
              <p className="cc-muted">No open mission right now. Add one to anchor your day.</p>
              <Link className="cc-btn cc-btn-primary cc-today-link-btn" to="/personal/productivity">
                Add mission
              </Link>
            </>
          )}
        </section>

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
                  {a.action_url ? (
                    <Link className="cc-today-alert-link" to={routeFromActionUrl(a.action_url)}>
                      Open
                    </Link>
                  ) : null}
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
    </div>
  );
}
