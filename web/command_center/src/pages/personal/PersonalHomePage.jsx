import { useCallback, useEffect, useRef, useState } from "react";

import { fetchPendingDecisions, fetchPersonalMorningBrief } from "../../api/commandCenterApi.js";
import { safeAsync } from "../../lib/safeAsync.js";

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    }).format(new Date(iso + "T12:00:00"));
  } catch {
    return iso;
  }
}

export default function PersonalHomePage() {
  const [vaultPass, setVaultPass] = useState("");
  const vaultRef = useRef("");
  const [brief, setBrief] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    vaultRef.current = vaultPass;
  }, [vaultPass]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const v = vaultRef.current?.trim() || undefined;
    try {
      const [b, d] = await Promise.all([
        fetchPersonalMorningBrief(v),
        fetchPendingDecisions(12).catch(() => ({ items: [] })),
      ]);
      setBrief(b);
      setDecisions(Array.isArray(d?.items) ? d.items : []);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Could not load morning brief.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    safeAsync(load, { toast: false })();
  }, [load]);

  const weather = brief?.weather;
  const fin = brief?.financial_snapshot || {};
  const health = brief?.health_score || {};

  return (
    <div className="personal-os-page">
      <div className="personal-os-hero">
        <div>
          <h1 className="personal-os-title">Daily command center</h1>
          <p className="personal-os-sub">{formatDate(brief?.date)}</p>
        </div>
        <div className="personal-os-vault">
          <label className="personal-os-label">
            Vault passphrase (optional — encrypts synced notes when saving health/finance)
            <input
              type="password"
              className="cc-input personal-os-input"
              value={vaultPass}
              onChange={(e) => setVaultPass(e.target.value)}
              placeholder="Leave empty if not using encrypted fields"
              autoComplete="off"
            />
          </label>
          <button type="button" className="cc-btn cc-btn-primary" onClick={() => load()} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <div className="personal-os-banner personal-os-banner--error">{String(error)}</div>}
      {loading && !brief && <p className="cc-muted">Loading your brief…</p>}

      {brief && (
        <div className="personal-os-grid">
          <section className="personal-os-card personal-os-card--wide">
            <h2 className="personal-os-card-title">Today at a glance</h2>
            <div className="personal-os-row">
              {weather?.temperature_c != null ? (
                <div>
                  <span className="personal-os-stat-label">Weather</span>
                  <span className="personal-os-stat-value">
                    {Number(weather.temperature_c).toFixed(0)}°C
                  </span>
                  <span className="cc-muted" style={{ display: "block", fontSize: 12 }}>
                    Code {weather.weather_code ?? "—"}
                  </span>
                </div>
              ) : (
                <div>
                  <span className="personal-os-stat-label">Weather</span>
                  <span className="cc-muted">Set PERSONAL_OS_WEATHER_LAT / LON on the server for live weather.</span>
                </div>
              )}
              <div>
                <span className="personal-os-stat-label">Cash out (today)</span>
                <span className="personal-os-stat-value">
                  {fin.currency || "INR"} {fin.spent_today ?? "0"}
                </span>
              </div>
              <div>
                <span className="personal-os-stat-label">Month spend</span>
                <span className="personal-os-stat-value">
                  {fin.currency || "INR"} {fin.spent_month ?? "0"}
                </span>
              </div>
              <div>
                <span className="personal-os-stat-label">Health score</span>
                <span className="personal-os-stat-value">
                  {health.score != null ? `${health.score}/100` : "—"}
                </span>
                {health.hint && (
                  <span className="cc-muted" style={{ display: "block", fontSize: 12 }}>
                    {health.hint}
                  </span>
                )}
              </div>
            </div>
          </section>

          <section className="personal-os-card">
            <h2 className="personal-os-card-title">Top 3 priorities</h2>
            <p className="cc-muted personal-os-hint">From open personal missions (P1 first).</p>
            <ol className="personal-os-list">
              {(brief.priorities || []).length === 0 && <li className="cc-muted">No open missions — add tasks in Life OS.</li>}
              {(brief.priorities || []).map((p) => (
                <li key={p.id}>
                  <span className={`personal-os-pill personal-os-pill--${(p.priority || "P2").toLowerCase()}`}>
                    {p.priority || "P2"}
                  </span>
                  {p.title}
                  {p.deadline && (
                    <span className="cc-muted" style={{ display: "block", fontSize: 12 }}>
                      Due {p.deadline}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </section>

          <section className="personal-os-card">
            <h2 className="personal-os-card-title">Upcoming EMIs</h2>
            <ul className="personal-os-list personal-os-list--plain">
              {(fin.upcoming_emis || []).length === 0 && (
                <li className="cc-muted">No loans with a next due date — add under Finance.</li>
              )}
              {(fin.upcoming_emis || []).map((e) => (
                <li key={e.id}>
                  <strong>{e.name}</strong>
                  <span className="cc-muted" style={{ marginLeft: 8 }}>
                    {e.due} {e.emi ? `· EMI ${e.emi}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <section className="personal-os-card">
            <h2 className="personal-os-card-title">Meetings</h2>
            <p className="cc-muted">
              {(brief.meetings || []).length === 0
                ? "Planner sync for today arrives in a later phase — use your calendar for now."
                : JSON.stringify(brief.meetings)}
            </p>
          </section>

          <section className="personal-os-card personal-os-card--wide">
            <h2 className="personal-os-card-title">Pending decisions</h2>
            {decisions.length === 0 ? (
              <p className="cc-muted">No pending decisions in Command Center.</p>
            ) : (
              <ul className="personal-os-list personal-os-list--plain">
                {decisions.slice(0, 8).map((d) => (
                  <li key={d.id}>
                    <strong>{d.action || "Decision"}</strong>
                    {d.entity ? <span className="cc-muted"> · {d.entity}</span> : null}
                    {d.created_at && (
                      <span className="cc-muted" style={{ display: "block", fontSize: 12 }}>
                        {d.created_at}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="personal-os-card personal-os-card--wide personal-os-card--insight">
            <h2 className="personal-os-card-title">Strategic insight</h2>
            <p className="personal-os-insight">{brief.ai_insight || "—"}</p>
          </section>
        </div>
      )}
    </div>
  );
}
