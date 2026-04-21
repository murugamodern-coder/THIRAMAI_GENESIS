import React, { useState } from 'react';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import { LoadingSkeleton, EmptyState } from '../../components/LoadingSkeleton';
import AgentApprovalPanel from '../../components/AgentApprovalPanel';
import { jarvisApi, osApi } from '../../services/api';

export default function ThiraiDashboard() {
  const [jarvisResponse, setJarvisResponse] = useState(null);
  const [jarvisLoading, setJarvisLoading] = useState(false);

  const handleJarvisAsk = async (question) => {
    setJarvisLoading(true);
    try {
      const data = await jarvisApi.ask(question, 'dashboard', 'stock');
      if (data?.task_id) {
        setJarvisResponse(
          `Plan: ${data.title || 'Agent mission'} · task ${data.task_id}${data.requires_approval ? ' — approve steps in the panel below.' : ''}`,
        );
      } else {
        setJarvisResponse(typeof data?.message === 'string' ? data.message : 'Plan received — check workflow panel.');
      }
    } catch (error) {
      setJarvisResponse('Error communicating with Jarvis.');
    } finally {
      setJarvisLoading(false);
    }
  };

  return (
    <div style={{ fontFamily: "var(--font-sans, system-ui)", padding: "0 0 40px" }}>
      <ErrorBoundary>
        {/* Jarvis Input Section */}
        <div style={{
          display: "flex", gap: 6,
          background: "var(--color-background-secondary)",
          borderRadius: 10, padding: "8px 10px",
          border: "0.5px solid var(--color-border-tertiary)",
          alignItems: "center",
        }}>
          <input
            placeholder="Ask Jarvis anything..."
            style={{
              background: "transparent", border: "none", outline: "none",
              fontSize: 12, color: "var(--color-text-primary)", flex: 1,
              fontFamily: "inherit",
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleJarvisAsk(e.target.value);
                e.target.value = '';
              }
            }}
          />

          {jarvisLoading && (
            <LoadingSkeleton rows={1} />
          )}

          {jarvisResponse && (
            <div style={{ marginTop: 8, background: "var(--color-background-secondary)", padding: 10, borderRadius: 8 }}>
              <div style={{ fontSize: 12, color: "var(--color-text-primary)" }}>{jarvisResponse}</div>
              <button onClick={() => setJarvisResponse(null)} style={{
                background: "transparent", color: "#E24B4A",
                border: "none", cursor: "pointer",
                fontSize: 12, marginTop: 4
              }}>Dismiss</button>
            </div>
          )}
        </div>
        <AgentApprovalPanel />
      </ErrorBoundary>
    </div>
  );
}
