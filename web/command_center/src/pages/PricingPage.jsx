import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { fetchProductPlans } from "../api/commandCenterApi.js";

export default function PricingPage() {
  const [plans, setPlans] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const out = await fetchProductPlans();
        if (!c && out?.plans) setPlans(out.plans);
      } catch (e) {
        if (!c) setErr(e?.message || "Could not load plans");
      }
    })();
    return () => {
      c = true;
    };
  }, []);

  return (
    <div className="cc-landing">
      <header className="cc-landing-top">
        <Link to="/" className="cc-brand" style={{ textDecoration: "none", color: "inherit" }}>
          THIRAMAI
        </Link>
        <nav className="cc-landing-nav">
          <Link className="cc-btn" to="/login">
            Sign in
          </Link>
          <Link className="cc-btn cc-btn-primary" to="/signup">
            Start free
          </Link>
        </nav>
      </header>
      <section className="cc-landing-hero">
        <h1>Plans that grow with you</h1>
        <p className="cc-landing-lead">Free to explore. Pro unlocks Jarvis agent, deep research, and auto accounting.</p>
      </section>
      {err && <p className="cc-error" style={{ padding: "0 24px" }}>{err}</p>}
      <section className="cc-landing-grid" aria-label="Plans">
        {plans.map((p) => (
          <div key={p.id} className="cc-landing-card">
            <h3>{p.name}</h3>
            <p style={{ fontSize: 22, fontWeight: 700 }}>
              {p.price_inr_month ? `₹${p.price_inr_month.toLocaleString("en-IN")} / mo` : "₹0"}
            </p>
            <p className="cc-muted">{p.tagline}</p>
            <ul style={{ paddingLeft: 18, marginTop: 8 }}>
              {(p.features || []).map((f) => (
                <li key={f} style={{ marginBottom: 6 }}>
                  {f}
                </li>
              ))}
            </ul>
            <Link className="cc-btn cc-btn-primary" style={{ marginTop: 12, display: "inline-block" }} to="/signup">
              {p.id === "free" ? "Start free" : "Contact us to upgrade"}
            </Link>
          </div>
        ))}
      </section>
      <footer className="cc-landing-footer">
        <span className="cc-muted">Billing provider wiring is a follow-up — today, plans gate premium APIs.</span>
      </footer>
    </div>
  );
}
