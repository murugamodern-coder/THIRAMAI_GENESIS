import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

function PipelineStage({ stage, title, description, agent, status }) {
  return (
    <div style={{
      background: "var(--color-background-secondary)",
      borderRadius: 8, padding: "10px",
      border: "1px solid var(--color-border-tertiary)",
      marginBottom: 16,
      flex: 1,
      marginRight: 8,
      textAlign: 'center',
    }}>
      <div style={{ fontSize: 18, fontWeight: 500, color: "var(--color-text-primary)" }}>{stage}. {title}</div>
      <div style={{ margin: "8px 0", fontSize: 12, color: "var(--color-text-tertiary)" }}>Agent: {agent}</div>
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>{description}</p>
      <div style={{ height: 10, width: 10, borderRadius: "50%", background: status === 'Idle' ? 'grey' : 'green', margin: "0 auto" }}></div>
    </div>
  );
}

function AISourceCard({ name, status, message }) {
  return (
    <div style={{
      background: "var(--color-background-secondary)",
      borderRadius: 8,
      border: "1px solid var(--color-border-tertiary)",
      padding: "10px",
      marginBottom: 8
    }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <div style={{ fontSize: 16, fontWeight: 500, color: "var(--color-text-primary)" }}>{name}</div>
        <span style={{ fontSize: 11, background: "#D85A3030", color: "var(--color-text-primary)", padding: "2px 6px", borderRadius: 10 }}>{status}</span>
      </div>
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>{message}</p>
    </div>
  );
}

export default function Research() {
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);

  return (
    <div style={{ padding: "20px", position: "relative" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <h1 style={{ color: "var(--color-text-primary)" }}>Research OS</h1>
        <button onClick={() => navigate(-1)} style={{
          background: "#D85A30",
          color: "#fff",
          borderRadius: 8,
          padding: "6px 12px",
          border: "none",
          cursor: "pointer"
        }}>Back</button>
        <button onClick={() => setShowModal(true)} style={{
          background: "#D85A30",
          color: "#fff",
          borderRadius: 8,
          padding: "6px 12px",
          border: "none",
          cursor: "pointer"
        }}>New Mission</button>
      </div>

      {/* Pipeline Visualiser */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 24 }}>
        <PipelineStage stage={1} title="Mission Decomposition" description="Break complex question into sub-tasks" agent="Lindy.ai / CrewAI" status="Idle" />
        <PipelineStage stage={2} title="Recursive Search" description="Deep web + database search per sub-task" agent="Perplexity API" status="Idle" />
        <PipelineStage stage={3} title="Synthesis & Verification" description="Combine results, cross-check facts" agent="GPT-5 + StormAI" status="Idle" />
        <PipelineStage stage={4} title="Logical Reasoning" description="Apply reasoning, identify gaps" agent="GPT-5" status="Idle" />
        <PipelineStage stage={5} title="Report Generation" description="Format final output: PDF / MD / HTML" agent="Custom template engine" status="Idle" />
      </div>

      {/* Active Missions & AI Stack */}
      <div style={{ display: "flex", marginBottom: 24 }}>
        <div style={{ flex: 0.6, paddingRight: 12 }}>
          <h3 style={{ color: "var(--color-text-primary)" }}>Active Missions</h3>
          <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>No missions running — click New Mission to start</p>
        </div>
        <div style={{ flex: 0.4, paddingLeft: 12 }}>
          <h3 style={{ color: "var(--color-text-primary)" }}>AI Stack Status</h3>
          <AISourceCard name="Perplexity API" status="Not connected" message="Add API key" />
          <AISourceCard name="StormAI" status="Not connected" message="Add API key" />
          <AISourceCard name="GPT-5 (OpenAI)" status="Not connected" message="Add API key" />
          <AISourceCard name="Lindy.ai" status="Not connected" message="Already set up in Personal OS" />
          <AISourceCard name="CrewAI" status="Not connected" message="Configure endpoint" />
        </div>
      </div>

      {/* Recent Reports */}
      <div style={{
        background: "var(--color-background-secondary)",
        borderRadius: 8,
        border: "1px solid var(--color-border-tertiary)",
        padding: "20px",
      }}>
        <div style={{ color: "var(--color-text-primary)", fontSize: 16, fontWeight: 500, marginBottom: 8 }}>Recent Reports</div>
        <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Completed research reports will appear here</p>
      </div>

      {/* New Mission Modal */}
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
            <h2>New Mission</h2>
            <input placeholder="Mission Title" style={{ width: "100%", marginBottom: 8, padding: 8 }} />
            <textarea placeholder="Research Question" style={{ width: "100%", marginBottom: 8, padding: 8 }} />
            <select style={{ width: "100%", marginBottom: 8, padding: 8 }}>
              <option>Quick (1)</option>
              <option>Standard (3)</option>
              <option>Deep (5)</option>
            </select>
            <button style={{
              background: "#D85A30",
              color: "#fff",
              borderRadius: 8,
              padding: "8px 12px",
              border: "none",
              cursor: "pointer"
            }}>Launch mission</button>
            <button onClick={() => setShowModal(false)} style={{
              background: "transparent",
              color: "#D85A30",
              borderRadius: 8,
              padding: "8px 12px",
              border: "2px solid #D85A30",
              cursor: "pointer",
              marginLeft: 8
            }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}