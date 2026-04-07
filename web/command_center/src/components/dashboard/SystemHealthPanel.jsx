export default function SystemHealthPanel({ snapshot }) {
  const counts = snapshot?.priority_counts || {};
  const hitl = snapshot?.pending_hitl || [];
  const alerts = snapshot?.alerts || [];

  return (
    <div className="cc-card">
      <h2>System health &amp; automation</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 16 }}>
        <div className="cc-kpi">
          <div className="label">Emergency queue</div>
          <div className="value">{counts.emergency ?? 0}</div>
          <div className="trend">Immediate escalation</div>
        </div>
        <div className="cc-kpi">
          <div className="label">Urgent</div>
          <div className="value">{counts.urgent ?? 0}</div>
          <div className="trend">Next actions due</div>
        </div>
        <div className="cc-kpi">
          <div className="label">Legacy HITL items</div>
          <div className="value">{hitl.length}</div>
          <div className="trend">Backlog to resolve</div>
        </div>
      </div>
      <p className="cc-muted" style={{ marginTop: 12 }}>
        Automation and orchestration run server-side; this panel surfaces priority tiers and alerts from the
        command-center snapshot.
      </p>
      {alerts.length > 0 && (
        <ul style={{ margin: "16px 0 0", paddingLeft: 18, fontSize: 13 }}>
          {alerts.slice(0, 8).map((a, i) => (
            <li key={i} style={{ marginBottom: 6 }}>
              {a}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
