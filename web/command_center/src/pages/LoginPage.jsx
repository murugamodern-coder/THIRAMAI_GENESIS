import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { fetchProductBootstrap, loginWithPassword } from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";
import { useCommandStore } from "../store/useCommandStore.js";

export default function LoginPage() {
  const navigate = useNavigate();
  const token = useCommandStore((s) => s.token);
  const setToken = useCommandStore((s) => s.setToken);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  if (token) return <Navigate to="/command-center" replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const out = await loginWithPassword(username.trim(), password);
      if (out?.access_token) setToken(out.access_token);
      showToastDedup({ type: "success", message: "Welcome back" });
      let dest = "/command-center";
      try {
        const boot = await fetchProductBootstrap();
        const ob = boot?.product_profile?.onboarding || {};
        if (!ob?.insights_done && boot?.hints && !boot.hints.onboarding_complete) {
          dest = "/onboarding";
        }
      } catch {
        /* default command center */
      }
      navigate(dest, { replace: true });
    } catch (err) {
      const d = err?.response?.data?.detail;
      const msg = typeof d === "string" ? d : "Login failed";
      setError(msg);
      showToastDedup({ type: "error", message: "Login failed" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="cc-login-page">
      <div className="cc-login-box">
        <h1>Sign in — Command Center</h1>
        <form onSubmit={onSubmit}>
          <div className="cc-field">
            <label htmlFor="cc-user">Email or username</label>
            <input
              id="cc-user"
              className="cc-input"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="cc-field">
            <label htmlFor="cc-pass">Password</label>
            <input
              id="cc-pass"
              type="password"
              className="cc-input"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="cc-error">{error}</p>}
          <button type="submit" className="cc-btn cc-btn-primary" style={{ width: "100%", marginTop: 8 }} disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p style={{ marginTop: 16, fontSize: 13 }}>
          New here? <Link to="/signup">Create an account</Link>
        </p>
        <p style={{ marginTop: 8, fontSize: 13 }}>
          <Link to="/">← Back to home</Link>
        </p>
        <p className="cc-muted" style={{ marginTop: 12, fontSize: 12 }}>
          OAuth2 password flow → JWT stored as <code>thiramai_jwt</code> for API calls.
        </p>
      </div>
    </div>
  );
}
