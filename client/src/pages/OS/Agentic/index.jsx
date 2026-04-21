import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ThiramaiGoalsWorkspace from './ThiramaiGoalsWorkspace';

function MetricCard({ label, value }) {
  return (
    <div style={{
      background: "var(--color-background-secondary)",
      borderRadius: 8, padding: "10px",
      border: "1px solid var(--color-border-tertiary)",
      marginRight: 10,
      flex: 1
    }}>
      <div style={{ fontSize: 16, fontWeight: 500, color: "var(--color-text-primary)" }}>{value}</div>
      <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>{label}</div>
    </div>
  );
}

function PlatformCard({ name, description, status, buttonText, onClick }) {
  return (
    <div style={{
      background: "var(--color-background-secondary)",
      borderRadius: 8,
      border: "1px solid var(--color-border-tertiary)",
      padding: "10px",
      marginBottom: 8,
      flex: 1,
      marginRight: 8,
    }}>
      <div style={{ fontSize: 16, fontWeight: 500, color: "var(--color-text-primary)" }}>{name}</div>
      <div style={{ margin: "8px 0", fontSize: 12, color: "var(--color-text-tertiary)" }}>{description}</div>
      <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginBottom: 8 }}>{status}</div>
      <button onClick={onClick} style={{
        background: "#993556",
        color: "#fff",
        borderRadius: 8,
        padding: "6px 12px",
        border: "none",
        cursor: "pointer"
      }}>{buttonText}</button>
    </div>
  );
}

function openLink(url) {
  window.location.href = url;
}

export default function Agentic() {
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);

  return (
    <div style={{ padding: "20px", position: "relative" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <h1 style={{ color: "var(--color-text-primary)" }}>Agentic Web OS</h1>
        <button onClick={() => navigate(-1)} style={{
          background: "#993556",
          color: "#fff",
          borderRadius: 8,
          padding: "6px 12px",
          border: "none",
          cursor: "pointer"
        }}>Back</button>
        <button onClick={() => setShowModal(true)} style={{
          background: "#993556",
          color: "#fff",
          borderRadius: 8,
          padding: "6px 12px",
          border: "none",
          cursor: "pointer"
        }}>New Project</button>
      </div>

      {/* Metric Cards */}
      <div style={{ display: "flex", marginBottom: 24 }}>
        <MetricCard label="Active projects" value="0" />
        <MetricCard label="Deployments today" value="0" />
        <MetricCard label="Agents running" value="0" />
      </div>

      <ThiramaiGoalsWorkspace />

      {/* Platform Cards */}
      <div style={{ display: "flex", overflowX: "auto", marginBottom: 24 }}>
        <PlatformCard name="Replit" description="Cloud IDE + hosting — build and run full apps" status="Not connected"
          buttonText="Connect Replit" onClick={() => navigate('/settings/os/agentic')} />
        <PlatformCard name="Cursor" description="AI-first code editor — pair programming with agents" status="Not connected"
          buttonText="Connect Cursor" onClick={() => navigate('/settings/os/agentic')} />
        <PlatformCard name="Lovable" description="Prompt-to-app builder — React apps from description" status="Not connected"
          buttonText="Connect Lovable" onClick={() => navigate('/settings/os/agentic')} />
        <PlatformCard name="bolt.new" description="Instant full-stack apps — StackBlitz powered" status="Not connected"
          buttonText="Open bolt.new" onClick={() => openLink('https://bolt.new')} />
        <PlatformCard name="v0.dev" description="UI generation — Vercel's React component builder" status="Not connected"
          buttonText="Open v0.dev" onClick={() => openLink('https://v0.dev')} />
      </div>

      {/* Project List */}
      <div style={{
        background: "var(--color-background-secondary)",
        borderRadius: 8,
        border: "1px solid var(--color-border-tertiary)",
        padding: "20px",
      }}>
        <div style={{ color: "var(--color-text-primary)", fontSize: 16, fontWeight: 500, marginBottom: 8 }}>No projects yet</div>
        <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Connect a platform above to start building</p>
        <div style={{ display: "flex", gap: 8 }}>
          <span style={pillStyle}>Replit</span>
          <span style={pillStyle}>Cursor</span>
          <span style={pillStyle}>Lovable</span>
          <span style={pillStyle}>bolt.new</span>
          <span style={pillStyle}>v0.dev</span>
        </div>
      </div>

      {/* New Project Modal */}
      {showModal && (
        <div style={{
          position: "absolute", top: 0, left: 0,
          width: "100%", height: "100%",
          backgroundColor: "rgba(0, 0, 0, 0.5)",
          display: "flex", alignItems: "center", justifyContent: "center"
        }}>
          <div style={{
            background: "#fff", padding: 20, borderRadius: 8,
            width: "80%", maxWidth: 500,
          }}>
            <h2>New Project</h2>
            <input placeholder="Project Name" style={{ width: "100%", marginBottom: 8, padding: 8 }} />
            <select style={{ width: "100%", marginBottom: 8, padding: 8 }}>
              <option>Replit</option>
              <option>Cursor</option>
              <option>Lovable</option>
              <option>bolt.new</option>
              <option>v0.dev</option>
            </select>
            <textarea placeholder="Description" style={{ width: "100%", marginBottom: 8, padding: 8 }} />
            <button style={{
              background: "#993556",
              color: "#fff",
              borderRadius: 8,
              padding: "8px 12px",
              border: "none",
              cursor: "pointer"
            }}>Create project</button>
            <button onClick={() => setShowModal(false)} style={{
              background: "transparent",
              color: "#993556",
              borderRadius: 8,
              padding: "8px 12px",
              border: "2px solid #993556",
              cursor: "pointer",
              marginLeft: 8
            }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

const pillStyle = {
  background: "#99355620",
  color: "#993556",
  padding: "4px 10px",
  borderRadius: 20,
  fontSize: 12,
};
