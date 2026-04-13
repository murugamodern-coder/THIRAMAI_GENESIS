import { Link, NavLink, Outlet } from "react-router-dom";

import MobileBottomNav from "../components/MobileBottomNav.jsx";

export default function PersonalShellLayout() {
  return (
    <div className="cc-app">
      <header className="cc-topbar">
        <Link className="cc-brand" to="/today" style={{ textDecoration: "none", color: "inherit" }}>
          THIRAMAI
        </Link>
        <span className="cc-muted" style={{ fontWeight: 600, color: "var(--cc-text)" }}>
          Personal Command Center
        </span>
        <nav className="cc-nav" aria-label="Personal OS">
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} end to="/today">
            Today
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} end to="/personal">
            Brief
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/personal/finance">
            Finance
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/personal/health">
            Health
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/personal/productivity">
            Productivity
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/personal/research">
            Research
          </NavLink>
          <NavLink className={({ isActive }) => (isActive ? "active" : undefined)} to="/personal/integrations">
            Integrations
          </NavLink>
        </nav>
        <Link to="/dashboard" className="cc-muted" style={{ marginLeft: "auto", fontSize: 13 }}>
          Business dashboard
        </Link>
      </header>
      <main className="cc-main personal-os-main">
        <Outlet />
      </main>
      <MobileBottomNav />
    </div>
  );
}
