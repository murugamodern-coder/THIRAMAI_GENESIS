import { Link } from "react-router-dom";

import AIAssistantPanel from "../components/dashboard/AIAssistantPanel.jsx";
import { isFeatureEnabled } from "../lib/featureFlags.js";

/** Dedicated AI chat surface for mobile bottom nav "AI" tab. */
export default function CopilotPage() {
  return (
    <div className="cc-copilot-page">
      <p className="cc-muted" style={{ marginBottom: 12, fontSize: 13 }}>
        <Link to="/today">← Today</Link>
        {" · "}
        <Link to="/dashboard">Business dashboard</Link>
      </p>
      {isFeatureEnabled("COPILOT_CHAT") && isFeatureEnabled("AI_ASSISTANT") ? (
        <AIAssistantPanel />
      ) : (
        <div className="cc-card cc-muted" style={{ fontSize: 14 }}>
          Copilot / Jarvis is temporarily unavailable (incident mode or feature flag).
        </div>
      )}
    </div>
  );
}
