import { useState } from "react";
import AIAssistantPanel from "../components/dashboard/AIAssistantPanel.jsx";

export default function BrainPage() {
  const [isLoading, setIsLoading] = useState(false);

  return (
    <div
      className="mx-auto flex min-h-[calc(100vh-10rem)] max-w-[720px] flex-col justify-center py-10"
      style={{ color: "#ffffff" }}
    >
      <AIAssistantPanel
        onLoadingChange={setIsLoading}
        subtitle="Thiramai Sovereign OS · AI Command Interface"
      />
      {isLoading && (
        <div
          style={{
            display: "flex",
            gap: "6px",
            padding: "12px",
            justifyContent: "center",
          }}
        >
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                background: "#3b82f6",
                animation: `pulse 1s ease-in-out ${i * 0.2}s infinite`,
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
