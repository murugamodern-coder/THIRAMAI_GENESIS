import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { fetchPersonalWeeklyReview } from "../../api/commandCenterApi.js";

export default function WeeklyReviewPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await fetchPersonalWeeklyReview();
      setData(d);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Could not load review");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return (
      <div className="cc-card" style={{ maxWidth: 720 }}>
        <p className="cc-muted">Building your week in review…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cc-card" style={{ maxWidth: 720 }}>
        <p className="cc-error">{error}</p>
        <button type="button" className="cc-btn cc-btn-primary" onClick={load}>
          Retry
        </button>
      </div>
    );
  }

  const pri = data?.next_week_priorities_suggested || [];

  return (
    <div className="cc-card" style={{ maxWidth: 720 }}>
      <h1 className="personal-os-title">Weekly review</h1>
      <p className="cc-muted">
        Last 7 days snapshot · auto-generated every time you open this page (Sunday ritual, any day).
      </p>

      <dl className="cc-today-dl" style={{ marginTop: 24 }}>
        <div>
          <dt>Tasks completed (week)</dt>
          <dd>{data?.tasks_completed_week ?? "—"}</dd>
        </div>
        <div>
          <dt>Open missions now</dt>
          <dd>{data?.tasks_open_now ?? "—"}</dd>
        </div>
        <div>
          <dt>Personal spend (week)</dt>
          <dd>₹{data?.personal_spend_week_inr ?? "—"}</dd>
        </div>
        <div>
          <dt>Health days logged</dt>
          <dd>{data?.health_logs_logged_days_approx ?? "—"}</dd>
        </div>
        <div>
          <dt>Meetings scheduled (week)</dt>
          <dd>{data?.meetings_scheduled_week ?? "—"}</dd>
        </div>
      </dl>

      <section style={{ marginTop: 28 }}>
        <h2 style={{ fontSize: 17 }}>Next week priorities (from your open missions)</h2>
        {pri.length === 0 ? (
          <p className="cc-muted">No open missions — add one in Productivity.</p>
        ) : (
          <ol style={{ marginTop: 12, paddingLeft: 20 }}>
            {pri.map((p, i) => (
              <li key={i} style={{ marginBottom: 8 }}>
                <strong>{p.title}</strong>
                {p.priority ? <span className="cc-muted"> · {p.priority}</span> : null}
              </li>
            ))}
          </ol>
        )}
        <Link className="cc-link-inline" to="/personal/productivity" style={{ display: "inline-block", marginTop: 12 }}>
          Manage missions
        </Link>
      </section>

      <p className="cc-muted" style={{ marginTop: 24, fontSize: 13 }}>
        <Link to="/today">← Back to Today</Link>
      </p>
    </div>
  );
}
