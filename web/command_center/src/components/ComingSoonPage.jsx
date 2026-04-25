export default function ComingSoonPage({
  title,
  description,
  icon,
  expectedDate,
  features = [],
}) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0a0f1e",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#ffffff",
        padding: "24px",
      }}
    >
      <div
        style={{
          background: "rgba(255,255,255,0.03)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: "16px",
          padding: "48px",
          textAlign: "center",
          maxWidth: "480px",
          width: "100%",
        }}
      >
        <div style={{ fontSize: "48px", lineHeight: 1, marginBottom: "18px" }}>{icon}</div>
        <h1
          style={{
            margin: 0,
            color: "#ffffff",
            fontSize: "24px",
            fontWeight: 600,
            letterSpacing: "0.01em",
          }}
        >
          {title}
        </h1>
        <p
          style={{
            margin: "12px 0 0",
            color: "#94a3b8",
            fontSize: "15px",
            lineHeight: 1.6,
          }}
        >
          {description}
        </p>

        {expectedDate ? (
          <p style={{ margin: "10px 0 0", color: "#60a5fa", fontSize: "13px", letterSpacing: "0.04em" }}>
            Expected: {expectedDate}
          </p>
        ) : null}

        {Array.isArray(features) && features.length > 0 ? (
          <ul
            style={{
              listStyle: "none",
              textAlign: "left",
              margin: "24px 0 0",
              padding: 0,
              display: "grid",
              gap: "10px",
            }}
          >
            {features.map((feature) => (
              <li key={feature} style={{ color: "#cbd5e1", fontSize: "14px" }}>
                <span style={{ color: "#60a5fa", marginRight: "8px" }}>?</span>
                {feature}
              </li>
            ))}
          </ul>
        ) : null}

        <button
          type="button"
          style={{
            marginTop: "28px",
            background: "rgba(59,130,246,0.22)",
            border: "1px solid rgba(96,165,250,0.45)",
            color: "#dbeafe",
            borderRadius: "10px",
            padding: "10px 18px",
            fontSize: "14px",
            cursor: "pointer",
          }}
        >
          Notify me
        </button>

        <p style={{ margin: "22px 0 0", color: "#64748b", fontSize: "12px" }}>
          Part of Thiramai Sovereign OS
        </p>
      </div>
    </div>
  );
}
