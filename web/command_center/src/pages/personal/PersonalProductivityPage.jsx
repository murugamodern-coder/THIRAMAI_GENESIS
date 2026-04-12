import { Link } from "react-router-dom";

export default function PersonalProductivityPage() {
  return (
    <div className="personal-os-page">
      <header className="personal-os-section-head">
        <h1 className="personal-os-title">Productivity hub</h1>
        <p className="personal-os-sub">
          Phase 2 will add Pomodoro, habit calendar, energy curves, and meeting effectiveness — wired to Life OS habits and
          Command Center analytics.
        </p>
      </header>
      <div className="personal-os-card">
        <p className="personal-os-body">
          For now, use the <Link to="/dashboard">business dashboard</Link> for missions and the Life OS APIs for habits and
          planner blocks.
        </p>
      </div>
    </div>
  );
}
