import React from 'react';
import { useNavigate } from 'react-router-dom';

function MetricCard({ label, value }) {
  return (
    <div style={{
      background: "var(--color-background-secondary)",
      borderRadius: 8, padding: "10px",
      border: "1px solid var(--color-border-tertiary)",
      marginBottom: 12,
    }}>
      <div style={{ fontSize: 16, fontWeight: 500, color: "var(--color-text-primary)" }}>{value}</div>
      <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>{label}</div>
    </div>
  );
}

function IntegrationCard({ name, status, description, onConnect }) {
  return (
    <div style={{
      background: "var(--color-background-secondary)",
      borderRadius: 8,
      border: "1px solid var(--color-border-tertiary)",
      padding: "10px",
      marginBottom: 8,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <div style={{ fontSize: 16, fontWeight: 500, color: "var(--color-text-primary)" }}>{name}</div>
        <span style={{ fontSize: 11, background: "#1D9E7530", color: "var(--color-text-primary)", padding: "2px 6px", borderRadius: 10 }}>{status}</span>
      </div>
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", margin: "8px 0" }}>{description}</p>
      <button onClick={onConnect} style={{
        background: "#1D9E75",
        color: "#fff",
        borderRadius: 8,
        padding: "6px 12px",
        border: "none",
        cursor: "pointer"
      }}>Configure</button>
    </div>
  );
}

function TaskList() {
  return (
    <div style={{ flex: 0.6, paddingRight: 12 }}>
      <h3 style={{ color: "var(--color-text-primary)" }}>Today's Tasks</h3>
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>No tasks yet — connect Lindy.ai to sync tasks</p>
      <button style={{
        background: "#1D9E75",
        color: "#fff",
        borderRadius: 8,
        padding: "6px 12px",
        marginTop: 20,
        border: "none",
        cursor: "pointer"
      }}>Add Task</button>
    </div>
  );
}

function Schedule() {
  return (
    <div style={{ flex: 0.4, paddingLeft: 12 }}>
      <h3 style={{ color: "var(--color-text-primary)" }}>Schedule</h3>
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Connect Motion or Reclaim to see your schedule</p>
      <div style={{ fontSize: 12, color: "var(--color-text-primary)", marginTop: 10 }}>
        {[...Array(13).keys()].map(i => (
          <div key={i} style={{ marginBottom: 4 }}> {8 + i}:00 </div>
        ))}
      </div>
    </div>
  );
}

export default function Personal() {
  const navigate = useNavigate();
  return (
    <div style={{ padding: "20px" }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        justifyContent: "space-between", marginBottom: 24
      }}>
        <h1 style={{ color: "var(--color-text-primary)" }}>Personal OS</h1>
        <button onClick={() => navigate(-1)} style={{
          background: "#1D9E75",
          color: "#fff",
          borderRadius: 8,
          padding: "6px 12px",
          border: "none",
          cursor: "pointer"
        }}>Back</button>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: '#1D9E75',
            marginLeft: 10
          }}/>
        </div>
      </div>

      {/* Metrics Row */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 24 }}>
        <MetricCard label="Tasks today" value="0" />
        <MetricCard label="Focus hours" value="0h" />
        <MetricCard label="Meetings" value="0" />
        <MetricCard label="Habits done" value="0" />
      </div>

      {/* Task and Schedule Row */}
      <div style={{ display: "flex", marginBottom: 24 }}>
        <TaskList />
        <Schedule />
      </div>

      {/* Integration Status Cards */}
      <IntegrationCard name="Lindy.ai" status="Not connected"
        description="AI automation — triggers, workflows, email handling"
        onConnect={() => navigate('/settings/os/personal')} />
      <IntegrationCard name="Motion" status="Not connected"
        description="AI calendar scheduling and task prioritisation"
        onConnect={() => navigate('/settings/os/personal')} />
      <IntegrationCard name="Reclaim.ai" status="Not connected"
        description="Smart scheduling — habits, tasks, meetings"
        onConnect={() => navigate('/settings/os/personal')} />
      <IntegrationCard name="Recall / Rewind" status="Not connected"
        description="AI memory — search everything you've seen"
        onConnect={() => navigate('/settings/os/personal')} />
    </div>
  );
}