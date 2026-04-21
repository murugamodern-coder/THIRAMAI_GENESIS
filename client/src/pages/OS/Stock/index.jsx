import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

function ChecklistCard({ number, title, score, status, description, color, sources, onConfigure }) {
  const getBarColor = (score) => {
    if (score < 40) return 'red';
    if (score <= 70) return 'amber';
    return 'green';
  };

  return (
    <div style={{
      background: "var(--color-background-secondary)",
      borderRadius: 8, padding: "10px",
      border: `3px solid ${color}`,
      marginBottom: 16,
      width: '100%',
      boxSizing: 'border-box'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 22, fontWeight: 500, color }}>{number}. {title}</div>
        <span style={{ fontSize: 11, background: "#BA751730", color: "var(--color-text-primary)", padding: "2px 6px", borderRadius: 10 }}>{status}</span>
      </div>
      <div style={{ height: 10, backgroundColor: '#ddd', borderRadius: 5, overflow: 'hidden', marginBottom: 8 }}>
        <div style={{ width: `${score}%`, height: '100%', backgroundColor: getBarColor(score) }}></div>
      </div>
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", margin: "8px 0" }}>{description}</p>
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", margin: "8px 0" }}><strong>Sources:</strong> {sources}</p>
      <button onClick={onConfigure} style={{
        background: "#378ADD",
        color: "#fff",
        borderRadius: 8,
        padding: "6px 12px",
        border: "none",
        cursor: "pointer"
      }}>Configure</button>
    </div>
  );
}

function DataSourceCard({ name, status, description }) {
  return (
    <div style={{
      background: "var(--color-background-secondary)",
      borderRadius: 8,
      border: "1px solid var(--color-border-tertiary)",
      padding: "10px",
      marginBottom: 8,
      flex: 1,
      marginRight: 8
    }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <div style={{ fontSize: 16, fontWeight: 500, color: "var(--color-text-primary)" }}>{name}</div>
        <span style={{ fontSize: 11, background: "#BA751730", color: "var(--color-text-primary)", padding: "2px 6px", borderRadius: 10 }}>{status}</span>
      </div>
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", margin: "8px 0" }}>{description}</p>
    </div>
  );
}

export default function Stock() {
  const navigate = useNavigate();
  const [lastUpdated, setLastUpdated] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setLastUpdated(lastUpdated => lastUpdated + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ padding: "20px" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <h1 style={{ color: "var(--color-text-primary)" }}>Stock OS</h1>
        <button onClick={() => navigate(-1)} style={{
          background: "#BA7517",
          color: "#fff",
          borderRadius: 8,
          padding: "6px 12px",
          border: "none",
          cursor: "pointer"
        }}>Back</button>
        <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Last updated: {lastUpdated} seconds ago</div>
      </div>

      {/* Checklist */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, marginBottom: 24 }}>
        <ChecklistCard number={1} title="Macro Economics" score={0} status="Not configured" 
          description="GDP, inflation, interest rates, central bank policy"
          color="#378ADD" sources="Bloomberg, RBI data, Fed data" 
          onConfigure={() => console.log('Configure Macro Economics')} />
        <ChecklistCard number={2} title="Order Flow" score={0} status="Not configured" 
          description="Institutional buy/sell, dark pool activity, FII/DII data"
          color="#BA7517" sources="Bloomberg Terminal, exchange data"
          onConfigure={() => console.log('Configure Order Flow')} />
        <ChecklistCard number={3} title="Fundamental Strength" score={0} status="Not configured" 
          description="Revenue growth, margins, debt levels, promoter holding"
          color="#1D9E75" sources="Screener.in, company filings, Quiver Quant"
          onConfigure={() => console.log('Configure Fundamental Strength')} />
        <ChecklistCard number={4} title="Geopolitical Risk" score={0} status="Not configured" 
          description="Border tensions, sanctions, oil price, currency risk"
          color="#D85A30" sources="FlightRadar24, Marine Traffic, news sentiment"
          onConfigure={() => console.log('Configure Geopolitical Risk')} />
      </div>

      {/* Data Source Status */}
      <div style={{ display: "flex", marginBottom: 24 }}>
        <DataSourceCard name="Bloomberg Terminal" status="Not connected" description="Requires API licence" />
        <DataSourceCard name="Aladdin (BlackRock)" status="Not connected" description="Enterprise access" />
        <DataSourceCard name="Quiver Quantitative" status="Not connected" description="Add API key in settings" />
        <DataSourceCard name="Orbital Insight" status="Not connected" description="Contact sales" />
        <DataSourceCard name="FlightRadar24" status="Not connected" description="Add API key" />
        <DataSourceCard name="Marine Traffic" status="Not connected" description="Add API key" />
      </div>

      {/* Signal Feed */}
      <div style={{
        background: "var(--color-background-secondary)",
        borderRadius: 8,
        border: "1px solid var(--color-border-tertiary)",
        padding: "20px",
      }}>
        <div style={{ color: "var(--color-text-primary)", fontSize: 16, fontWeight: 500, marginBottom: 8 }}>Signal Feed</div>
        <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>No signals yet — connect data sources to begin analysis</p>
      </div>
    </div>
  );
}
