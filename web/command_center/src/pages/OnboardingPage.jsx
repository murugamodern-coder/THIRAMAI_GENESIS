import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import {
  fetchAuthMe,
  fetchProductBootstrap,
  postProductDemoSeed,
  postProductOnboarding,
  postUsageEvent,
} from "../api/commandCenterApi.js";
import { isOnboardingDone, setOnboardingDone } from "../lib/onboarding.js";
import { showToastDedup } from "../lib/toastDedup.js";
import { useCommandStore } from "../store/useCommandStore.js";

const STEPS = [
  {
    key: "business",
    title: "Your business workspace is live",
    body: "We created your organization and owner role. You can rename details later in settings — you are already inside a secure, tenant-scoped workspace.",
    cta: null,
  },
  {
    key: "demo",
    title: "Load demo data (optional)",
    body: "Adds one sample expense and one sample mission so charts and Today feel alive instantly. Remove anytime by deleting those rows.",
    cta: "demo",
  },
  {
    key: "expense",
    title: "Add a real expense",
    body: "Track one real spend so personal finance and cross-domain insights have signal.",
    cta: "expense",
  },
  {
    key: "insights",
    title: "Open Today for AI insights",
    body: "Your Today page shows weather, meetings, business snapshot, and System intelligence — powered by your data.",
    cta: "today",
  },
];

export default function OnboardingPage() {
  const navigate = useNavigate();
  const token = useCommandStore((s) => s.token);
  const setMe = useCommandStore((s) => s.setMe);
  const [step, setStep] = useState(0);
  const [userId, setUserId] = useState(null);
  const [orgName, setOrgName] = useState("");
  const [loading, setLoading] = useState(true);
  const [demoBusy, setDemoBusy] = useState(false);

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
        setOrgName(me.organization?.name || "");
        if (uid > 0 && isOnboardingDone(uid)) {
          navigate("/command-center", { replace: true });
          return;
        }
        const boot = await fetchProductBootstrap().catch(() => null);
        if (boot?.hints?.onboarding_complete) {
          navigate("/command-center", { replace: true });
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
  const content = STEPS[step];

  async function finish() {
    if (userId != null && userId > 0) {
      setOnboardingDone(userId, true);
      try {
        await postProductOnboarding({ insights_done: true, wow_ack: false });
        await postUsageEvent("onboarding_complete", { source: "command_center" });
      } catch {
        /* non-blocking */
      }
    }
    navigate("/command-center", { replace: true });
  }

  async function runDemo() {
    setDemoBusy(true);
    try {
      const out = await postProductDemoSeed();
      if (out?.ok) {
        showToastDedup({ type: "success", message: out.note === "already_seeded" ? "Demo already loaded" : "Demo data loaded" });
      } else {
        showToastDedup({ type: "warning", message: out?.error || "Could not load demo" });
      }
    } catch {
      showToastDedup({ type: "error", message: "Demo seed failed" });
    } finally {
      setDemoBusy(false);
    }
  }

  return (
    <div className="cc-onboarding">
      <div className="cc-onboarding-card">
        <div
          className="cc-onboarding-progress"
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className="cc-onboarding-progress-bar" style={{ width: `${progress}%` }} />
        </div>
        <p className="cc-muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Step {step + 1} of {STEPS.length}
        </p>
        <h1 className="cc-onboarding-title">{content.title}</h1>
        <p className="cc-onboarding-body">
          {content.key === "business" && orgName ? (
            <>
              <strong>{orgName}</strong> — {content.body}
            </>
          ) : (
            content.body
          )}
        </p>
        {content.cta === "demo" && (
          <div style={{ marginTop: 12 }}>
            <button type="button" className="cc-btn cc-btn-primary" disabled={demoBusy} onClick={runDemo}>
              {demoBusy ? "Loading…" : "Load sample data"}
            </button>
          </div>
        )}
        {content.cta === "expense" && (
          <div style={{ marginTop: 12 }}>
            <Link className="cc-btn cc-btn-primary" to="/personal/finance">
              Log an expense
            </Link>
          </div>
        )}
        <div className="cc-onboarding-actions">
          {step > 0 && (
            <button type="button" className="cc-btn" onClick={() => setStep((s) => Math.max(0, s - 1))}>
              Back
            </button>
          )}
          <button
            type="button"
            className="cc-btn cc-btn-primary"
            onClick={() => {
              if (last) finish();
              else setStep((s) => s + 1);
            }}
          >
            {last ? "Go to Today" : "Continue"}
          </button>
        </div>
        <p style={{ marginTop: 20, fontSize: 13 }}>
          <button type="button" className="cc-link-btn" onClick={() => navigate("/command-center", { replace: true })}>
            Skip for now
          </button>
          {" · "}
          <Link to="/pricing">Compare plans</Link>
        </p>
      </div>
    </div>
  );
}
