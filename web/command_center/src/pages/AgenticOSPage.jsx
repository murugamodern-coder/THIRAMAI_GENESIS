export default function AgenticOSPage() {
  return (
    <div>
      <h1 className="cc-page-title">Agentic Web OS</h1>
      <p className="cc-muted">Agentic development and deployment platform</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 14, marginTop: 24 }}>
        {[
          {
            name: "Replit",
            desc: "Cloud IDE + hosting — build and run full apps",
            url: "https://replit.com",
            color: "#F5A623",
          },
          {
            name: "Cursor",
            desc: "AI-first code editor — pair programming with agents",
            url: "https://cursor.sh",
            color: "#1D9E75",
          },
          {
            name: "Lovable",
            desc: "Prompt-to-app builder — React apps from description",
            url: "https://lovable.dev",
            color: "#993556",
          },
          {
            name: "bolt.new",
            desc: "Instant full-stack apps — StackBlitz powered",
            url: "https://bolt.new",
            color: "#378ADD",
          },
          {
            name: "v0.dev",
            desc: "UI generation — Vercel's React component builder",
            url: "https://v0.dev",
            color: "#000",
          },
        ].map((p) => (
          <div
            key={p.name}
            className="cc-card"
            onClick={() => window.open(p.url, "_blank")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                window.open(p.url, "_blank");
              }
            }}
            style={{ cursor: "pointer", borderTop: `3px solid ${p.color}` }}
          >
            <div style={{ fontSize: 18, fontWeight: 700, color: p.color, marginBottom: 6 }}>{p.name}</div>
            <div style={{ fontSize: 12, color: "var(--cc-muted,#888)", marginBottom: 12 }}>{p.desc}</div>
            <div style={{ fontSize: 12, color: p.color, fontWeight: 500 }}>Open platform →</div>
          </div>
        ))}
      </div>
    </div>
  );
}
