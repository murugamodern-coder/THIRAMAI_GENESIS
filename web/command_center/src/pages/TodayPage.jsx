import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { fetchPersonalTodayBrief } from "../api/commandCenterApi.js";

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

export default function TodayPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(() => new Date());

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

  const greeting = data?.greeting?.display_name || "there";
  const hour = now.getHours();
  const salute = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  if (loading && !data) {
    return (
      <div className="cc-today-page">
        <p className="cc-muted">Loading your day…</p>
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

  const weather = data?.weather;
  const weatherLine = data?.weather_configured ? weatherLabel(weather) : null;
  const focus = data?.focus_task;
  const meetings = data?.meetings_today || [];
  const health = data?.health_score_yesterday;
  const biz = data?.business_snapshot;
  const alerts = data?.proactive_alerts || [];
  const insight = data?.motivational_insight || "";

  return (
    <div className="cc-today-page">
      <header className="cc-today-hero">
        <div>
          <h1 className="cc-today-greeting">
            {salute}, {greeting}
          </h1>
          <p className="cc-today-sub">
            <span className="cc-today-date">{formatLongDate(data?.date)}</span>
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
        </div>
        <button type="button" className="cc-btn" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <div className="cc-today-grid">
        <section className="cc-card cc-today-focus">
          <h2 className="cc-today-card-title">Your focus</h2>
          {focus ? (
            <>
              <p className="cc-today-focus-priority">{focus.priority || "P2"}</p>
              <p className="cc-today-focus-title">{focus.title}</p>
              {focus.deadline && (
                <p className="cc-muted" style={{ fontSize: 13, marginTop: 8 }}>
                  Due {new Date(focus.deadline).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
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
                    {m.meeting_type ? ` · ${m.meeting_type}` : ""}
                  </div>
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
            </dl>
          ) : (
            <p className="cc-muted">No org revenue data, or you&apos;re in personal-only mode.</p>
          )}
          <Link className="cc-link-inline" to="/dashboard">
            Open business dashboard
          </Link>
        </section>

        <section className="cc-card cc-today-alerts">
          <h2 className="cc-today-card-title">Heads-up</h2>
          {alerts.length === 0 ? (
            <p className="cc-muted">You&apos;re clear — no urgent nudges right now.</p>
          ) : (
            <ul className="cc-today-alert-list">
              {alerts.map((a, i) => (
                <li key={`${a.code}-${i}`} className={`cc-today-alert cc-today-alert--${a.severity || "medium"}`}>
                  {a.message}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="cc-card cc-today-insight">
          <h2 className="cc-today-card-title">Insight</h2>
          <p className="cc-today-insight-text">{insight || "Stay consistent today — small steps compound."}</p>
        </section>
      </div>
    </div>
  );
}
