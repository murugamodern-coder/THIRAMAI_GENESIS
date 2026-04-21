export default function StockOSPage() {
  return (
    <div>
      <h1 className="cc-page-title">Stock OS — Market Intelligence</h1>
      <p className="cc-muted">Institutional-grade market intelligence · Second-to-second analysis</p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 24 }}>
        {[
          {
            n: "1. Macro-Economics",
            d: "GDP, inflation, interest rates, central bank policy",
            s: "Bloomberg, RBI data",
          },
          {
            n: "2. Order Flow",
            d: "Institutional buy/sell, dark pool, FII/DII data",
            s: "Bloomberg Terminal",
          },
          {
            n: "3. Fundamental Strength",
            d: "Revenue, margins, debt, promoter holding",
            s: "Screener.in, Quiver Quant",
          },
          {
            n: "4. Geopolitical Risk",
            d: "Border tensions, sanctions, oil price, currency risk",
            s: "FlightRadar24, Marine Traffic",
          },
        ].map((c) => (
          <div key={c.n} className="cc-card" style={{ borderLeft: "3px solid #BA7517" }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#BA7517", marginBottom: 6 }}>{c.n}</div>
            <div style={{ fontSize: 12, color: "var(--cc-muted,#888)", marginBottom: 8 }}>{c.d}</div>
            <div style={{ fontSize: 11, color: "var(--cc-muted,#aaa)" }}>Sources: {c.s}</div>
            <div style={{ marginTop: 12, height: 4, background: "#f0f0f0", borderRadius: 2 }}>
              <div style={{ width: "0%", height: "100%", background: "#BA7517", borderRadius: 2 }} />
            </div>
            <div style={{ fontSize: 11, color: "#BA7517", marginTop: 4 }}>Score: 0/100 — Connect data sources</div>
          </div>
        ))}
      </div>
      <div className="cc-card" style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Data Sources</h2>
        {[
          "Bloomberg Terminal",
          "Aladdin (BlackRock)",
          "Quiver Quantitative",
          "Orbital Insight",
          "FlightRadar24",
          "Marine Traffic",
        ].map((s) => (
          <div
            key={s}
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "10px 0",
              borderBottom: "1px solid var(--cc-border,#e5e7eb)",
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 500 }}>{s}</span>
            <span style={{ fontSize: 11, color: "#E24B4A", background: "#E24B4A15", padding: "2px 10px", borderRadius: 20 }}>
              Not connected
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
