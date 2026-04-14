import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { createOrganization } from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";
import { useCommandStore } from "../store/useCommandStore.js";

export default function SignupPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const inviteRef = (searchParams.get("ref") || "").trim();
  const token = useCommandStore((s) => s.token);
  const setToken = useCommandStore((s) => s.setToken);
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [plan, setPlan] = useState("free");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  if (token) return <Navigate to="/today" replace />;

  async function submit() {
    setError(null);
    setLoading(true);
    try {
      const out = await createOrganization({
        email: email.trim(),
        password,
        organization_name: orgName.trim(),
        plan,
        invite_code: inviteRef || null,
      });
      if (out?.access_token) setToken(out.access_token);
      showToastDedup({ type: "success", message: "Workspace created" });
      navigate("/onboarding", { replace: true });
    } catch (err) {
      const d = err?.response?.data?.detail;
      const msg =
        typeof d === "string"
          ? d
          : err?.response?.status === 409
            ? "That email is already registered. Try signing in."
            : "Could not create your organization. Check your network and try again.";
      setError(msg);
      showToastDedup({
        type: "error",
        message: "Signup failed",
        actionLabel: "Retry",
        onAction: () => submit(),
      });
    } finally {
      setLoading(false);
    }
  }

  async function onSubmit(e) {
    e.preventDefault();
    await submit();
  }

  return (
    <div className="cc-login-page">
      <div className="cc-login-box" style={{ maxWidth: 440 }}>
        <h1>Create your workspace</h1>
        <p className="cc-muted" style={{ marginTop: -8, marginBottom: 16 }}>
          Creates your organization, owner account, and roles — same as product onboarding API{" "}
          <code style={{ fontSize: 11 }}>/org/create</code>.
          {inviteRef ? (
            <>
              {" "}
              Referral code <code>{inviteRef}</code> will be attached.
            </>
          ) : null}
        </p>
        <form onSubmit={onSubmit}>
          <div className="cc-field">
            <label htmlFor="su-org">Organization name</label>
            <input
              id="su-org"
              className="cc-input"
              autoComplete="organization"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="Acme Pvt Ltd"
              required
              minLength={1}
            />
          </div>
          <div className="cc-field">
            <label htmlFor="su-email">Work email</label>
            <input
              id="su-email"
              type="email"
              className="cc-input"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="cc-field">
            <label htmlFor="su-pass">Password (min 8 characters)</label>
            <input
              id="su-pass"
              type="password"
              className="cc-input"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>
          <div className="cc-field">
            <label htmlFor="su-plan">Plan</label>
            <select id="su-plan" className="cc-select" value={plan} onChange={(e) => setPlan(e.target.value)}>
              <option value="free">Free</option>
              <option value="pro">Pro</option>
              <option value="business">Business</option>
              <option value="enterprise">Enterprise (legacy)</option>
            </select>
          </div>
          {error && <p className="cc-error">{error}</p>}
          <button type="submit" className="cc-btn cc-btn-primary" style={{ width: "100%", marginTop: 8 }} disabled={loading}>
            {loading ? "Creating workspace…" : "Create workspace"}
          </button>
        </form>
        <p style={{ marginTop: 16, fontSize: 13 }}>
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
        <p style={{ marginTop: 8, fontSize: 13 }}>
          <Link to="/">← Back to home</Link>
        </p>
      </div>
    </div>
  );
}
