import { isIncidentMode } from "../lib/incidentMode.js";

export default function IncidentBanner() {
  if (!isIncidentMode()) return null;
  return (
    <div
      role="status"
      style={{
        padding: "8px 16px",
        background: "rgba(245, 158, 11, 0.15)",
        borderBottom: "1px solid rgba(245, 158, 11, 0.4)",
        fontSize: 13,
        textAlign: "center",
      }}
    >
      <strong>Incident mode:</strong> heavy features are reduced to protect the platform. Thank you for your patience.
    </div>
  );
}
