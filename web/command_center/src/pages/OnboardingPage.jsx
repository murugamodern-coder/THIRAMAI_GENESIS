import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { fetchAuthMe, postUsageEvent } from "../api/commandCenterApi.js";
import { isOnboardingDone, setOnboardingDone } from "../lib/onboarding.js";
import { useCommandStore } from "../store/useCommandStore.js";

const STEPS = [
  {
    title: "Welcome to your command center",
    body: "You now have a dedicated workspace with roles and tenant isolation. Everything you see is scoped to your organization.",
  },
  {
    title: "See the business in one screen",
    body: "Open the dashboard for KPIs, financial charts, AI approval queue, and system health. That is your daily cockpit.",
  },
  {
    title: "Ask THIRAMAI",
    body: "Use the AI assistant panel for natural-language questions. Sensitive actions may require your approval in Mission Hub.",
  },
  {
    title: "You are ready",
    body: "Explore Inventory, Billing, and Production from the top navigation when your team is ready to go live.",
  },
];

export default function OnboardingPage() {
  const navigate = useNavigate();
  const token = useCommandStore((s) => s.token);
  const setMe = useCommandStore((s) => s.setMe);
  const [step, setStep] = useState(0);
  const [userId, setUserId] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const me = await fetchAuthMe();
        if (cancelled || !me) return;
        setMe(me);
        const uid = me.id;
        setUserId(uid);
        if (uid > 0 && isOnboardingDone(uid)) {
          navigate("/today", { replace: true });
          return;
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, navigate, setMe]);

  if (!token) return <Navigate to="/login" replace />;
  if (loading) {
    return (
      <div className="cc-login-page">
        <p className="cc-muted">Loading your profile…</p>
      </div>
    );
  }

  const last = step === STEPS.length - 1;
  const progress = Math.round(((step + 1) / STEPS.length) * 100);

  async function finish() {
    if (userId != null && userId > 0) {
      setOnboardingDone(userId, true);
      try {
        await postUsageEvent("onboarding_complete", { source: "command_center" });
      } catch {
        /* non-blocking */
      }
    }
    navigate("/today", { replace: true });
  }

  function next() {
    if (last) {
      finish();
      return;
    }
    setStep((s) => s + 1);
  }

  function back() {
    setStep((s) => Math.max(0, s - 1));
  }

  const content = STEPS[step];

  return (
    <div className="cc-onboarding">
      <div className="cc-onboarding-card">
        <div className="cc-onboarding-progress" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
          <div className="cc-onboarding-progress-bar" style={{ width: `${progress}%` }} />
        </div>
        <p className="cc-muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Step {step + 1} of {STEPS.length}
        </p>
        <h1 className="cc-onboarding-title">{content.title}</h1>
        <p className="cc-onboarding-body">{content.body}</p>
        <div className="cc-onboarding-actions">
          {step > 0 && (
            <button type="button" className="cc-btn" onClick={back}>
              Back
            </button>
          )}
          <button type="button" className="cc-btn cc-btn-primary" onClick={next}>
            {last ? "Go to dashboard" : "Continue"}
          </button>
        </div>
        <p style={{ marginTop: 20, fontSize: 13 }}>
          <button
            type="button"
            className="cc-link-btn"
            onClick={() => finish()}
          >
            Skip for now
          </button>
        </p>
      </div>
    </div>
  );
}
