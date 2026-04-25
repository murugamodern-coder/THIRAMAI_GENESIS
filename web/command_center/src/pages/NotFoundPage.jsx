import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0a0f1e",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      <div
        style={{
          maxWidth: "520px",
          width: "100%",
          borderRadius: "16px",
          border: "1px solid rgba(255,255,255,0.08)",
          background: "rgba(255,255,255,0.03)",
          textAlign: "center",
          padding: "48px",
        }}
      >
        <div
          style={{
            margin: 0,
            fontSize: "72px",
            fontWeight: 800,
            letterSpacing: "0.04em",
            background: "linear-gradient(120deg, #60a5fa 0%, #a78bfa 50%, #22d3ee 100%)",
            WebkitBackgroundClip: "text",
            backgroundClip: "text",
            color: "transparent",
          }}
        >
          404
        </div>
        <h1 style={{ margin: "8px 0 0", color: "#ffffff", fontSize: "26px", fontWeight: 600 }}>Page not found</h1>
        <p style={{ margin: "12px 0 0", color: "#94a3b8", fontSize: "15px", lineHeight: 1.6 }}>
          The page you requested does not exist or has moved inside Thiramai Sovereign OS.
        </p>
        <Link
          to="/command-center"
          style={{
            marginTop: "24px",
            display: "inline-block",
            textDecoration: "none",
            color: "#dbeafe",
            border: "1px solid rgba(96,165,250,0.45)",
            background: "rgba(59,130,246,0.2)",
            borderRadius: "10px",
            padding: "10px 16px",
            fontSize: "14px",
            fontWeight: 500,
          }}
        >
          Go to Command Center
        </Link>
      </div>
    </div>
  );
}
