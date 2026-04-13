import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  fetchGoogleCalendarStatus,
  postGoogleCalendarConnect,
  postGoogleCalendarSync,
} from "../../api/commandCenterApi.js";
import { showToastDedup } from "../../lib/toastDedup.js";

export default function PersonalIntegrationsPage() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const s = await fetchGoogleCalendarStatus();
      setStatus(s);
    } catch {
      setStatus({ connected: false, oauth_configured: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const gcal = params.get("gcal");
    const err = params.get("gcal_error");
    if (gcal === "connected") {
      showToastDedup({ type: "success", message: "Google Calendar connected" });
      setParams({}, { replace: true });
      load();
    }
    if (err) {
      showToastDedup({ type: "error", message: `Google: ${decodeURIComponent(err)}` });
      setParams({}, { replace: true });
    }
  }, [params, setParams, load]);

  async function connectGoogle() {
    try {
      const out = await postGoogleCalendarConnect();
      const url = out?.authorization_url;
      if (!url) {
        showToastDedup({ type: "error", message: "No authorization URL returned" });
        return;
      }
      window.location.href = url;
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Connect failed" });
    }
  }

  async function syncNow() {
    setSyncing(true);
    try {
      const out = await postGoogleCalendarSync();
      showToastDedup({
        type: "success",
        message: `Synced ${out?.pushed ?? 0} meeting(s)`,
      });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Sync failed" });
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="cc-card" style={{ maxWidth: 640 }}>
      <h1>Integrations</h1>
      <p className="cc-muted">Connect external services to THIRAMAI.</p>

      <section style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 16 }}>Google Calendar</h2>
        <p className="cc-muted" style={{ fontSize: 14 }}>
          New meetings created in THIRAMAI can be pushed to your Google primary calendar when connected.
        </p>
        {loading ? (
          <p className="cc-muted">Loading status…</p>
        ) : (
          <>
            <p style={{ marginTop: 12 }}>
              <strong>OAuth configured (server):</strong> {status?.oauth_configured ? "Yes" : "No"}
            </p>
            <p>
              <strong>Connected:</strong> {status?.connected ? "Yes" : "No"}
            </p>
            {status?.last_synced_at && (
              <p className="cc-muted" style={{ fontSize: 13 }}>
                Last sync: {new Date(status.last_synced_at).toLocaleString()}
              </p>
            )}
            <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 12 }}>
              <button type="button" className="cc-btn cc-btn-primary" onClick={connectGoogle}>
                Connect Google Calendar
              </button>
              <button
                type="button"
                className="cc-btn"
                disabled={!status?.connected || syncing}
                onClick={syncNow}
              >
                {syncing ? "Syncing…" : "Sync meetings now"}
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
