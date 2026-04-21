import { Link } from "react-router-dom";

import FourPointEngineStrip from "./FourPointEngineStrip.jsx";
import Badge from "../ui/Badge.jsx";
import Card from "../ui/Card.jsx";

function statusVariant(status) {
  if (status === "healthy") return "success";
  if (status === "degraded") return "warning";
  return "error";
}

export default function OSModuleTile({ module }) {
  const metrics = Array.isArray(module?.quickMetrics) ? module.quickMetrics : [];
  const activity = module?.agentActivity || {};

  return (
    <Card
      title={module?.title || "OS Module"}
      subtitle={module?.description || ""}
      className="cc-os-tile"
      actions={
        <Badge variant={statusVariant(module?.liveStatus)} dot size="sm">
          {module?.liveStatus || "offline"}
        </Badge>
      }
      footer={
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span className="cc-muted" style={{ fontSize: 12 }}>
            {module?.statusDetail || "No status available"}
          </span>
          <Link className="cc-btn cc-btn-primary" to={module?.route || "/dashboard"}>
            Open module
          </Link>
        </div>
      }
    >
      <div style={{ display: "grid", gap: 10 }}>
        {metrics.length > 0 ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
            {metrics.slice(0, 3).map((metric) => (
              <div key={metric.label} className="cc-kpi" style={{ margin: 0, padding: 10 }}>
                <div className="cc-muted" style={{ fontSize: 11 }}>
                  {metric.label}
                </div>
                <div style={{ fontWeight: 700, marginTop: 2 }}>{metric.value ?? "—"}</div>
              </div>
            ))}
          </div>
        ) : null}
        <div className="cc-card" style={{ margin: 0, padding: 10 }}>
          <div className="cc-muted" style={{ fontSize: 12 }}>
            Agent activity
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginTop: 4 }}>
            <strong>{activity?.activeAgents ?? 0} active</strong>
            <span className="cc-muted" style={{ fontSize: 12 }}>
              {activity?.lastEvent || "Awaiting signal"}
            </span>
          </div>
        </div>
        {module?.fourPointEngine ? (
          <div className="cc-card" style={{ margin: 0, padding: 10 }}>
            <div className="cc-muted" style={{ fontSize: 12, marginBottom: 6 }}>
              4-point realtime engine
            </div>
            <FourPointEngineStrip engine={module.fourPointEngine} />
          </div>
        ) : null}
      </div>
    </Card>
  );
}
