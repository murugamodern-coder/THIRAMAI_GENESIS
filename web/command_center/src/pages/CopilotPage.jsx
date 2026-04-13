import { Link } from "react-router-dom";

import AIAssistantPanel from "../components/dashboard/AIAssistantPanel.jsx";

/** Dedicated AI chat surface for mobile bottom nav "AI" tab. */
export default function CopilotPage() {
  return (
    <div className="cc-copilot-page">
      <p className="cc-muted" style={{ marginBottom: 12, fontSize: 13 }}>
        <Link to="/today">← Today</Link>
        {" · "}
        <Link to="/dashboard">Business dashboard</Link>
      </p>
      <AIAssistantPanel />
    </div>
  );
}
