import { Link } from "react-router-dom";

import { useCommandStore } from "../store/useCommandStore.js";

export default function LandingPage() {
  const token = useCommandStore((s) => s.token);

  return (
    <div className="cc-landing">
      <header className="cc-landing-top">
        <span className="cc-brand">THIRAMAI</span>
        <nav className="cc-landing-nav">
          <Link className="cc-btn" to="/pricing">
            Pricing
          </Link>
          {token ? (
            <Link className="cc-btn cc-btn-primary" to="/today">
              Open command center
            </Link>
          ) : (
            <>
              <Link className="cc-btn" to="/login">
                Sign in
              </Link>
              <Link className="cc-btn cc-btn-primary" to="/signup">
                Create account
              </Link>
            </>
          )}
        </nav>
      </header>

      <section className="cc-landing-hero">
        <h1>AI that runs your business + life</h1>
        <p className="cc-landing-lead">
          One OS for revenue, inventory, personal cash flow, and Jarvis — the agent that asks before it acts. Built
          for Indian SMBs who want clarity without juggling ten apps.
        </p>
        {!token && (
          <div className="cc-landing-cta">
            <Link className="cc-btn cc-btn-primary cc-landing-cta-main" to="/signup">
              Start free
            </Link>
            <Link className="cc-btn" to="/login">
              I already have an account
            </Link>
          </div>
        )}
      </section>

      <section className="cc-landing-card" style={{ maxWidth: 560, margin: "0 auto 24px", padding: 20 }}>
        <h3 style={{ marginTop: 0 }}>Invite a co-founder</h3>
        <p className="cc-muted" style={{ marginBottom: 12 }}>
          After you sign in, use <strong>Today → Share THIRAMAI</strong> (or the invite API) to copy a referral link.
          Each signup helps your workspace grow faster.
        </p>
      </section>

      <section className="cc-landing-grid" aria-label="What you get">
        <div className="cc-landing-card">
          <h3>Unified dashboard</h3>
          <p>Revenue, stock risk, and AI approvals in one enterprise-style view.</p>
        </div>
        <div className="cc-landing-card">
          <h3>AI that asks before it acts</h3>
          <p>Approve or reject proposed actions — your rules, your tenant boundary.</p>
        </div>
        <div className="cc-landing-card">
          <h3>Multi-org ready</h3>
          <p>Switch organizations when you belong to more than one workspace.</p>
        </div>
      </section>

      <footer className="cc-landing-footer">
        <span className="cc-muted">THIRAMAI Genesis — sovereign AI operations</span>
      </footer>
    </div>
  );
}
