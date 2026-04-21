import React, { useCallback, useEffect, useRef, useState } from 'react';
import { agentApi, ensureAgentCorrelationId } from '../services/api';

function notifyPendingApproval(taskId, title) {
  const msg = title ? `Jarvis needs approval: ${title}` : 'Jarvis needs your approval to continue.';
  // eslint-disable-next-line no-console
  console.info('[Jarvis]', msg, { task_id: taskId });
  if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
    try {
      new Notification('THIRAMAI · Jarvis', { body: msg.slice(0, 180), tag: taskId });
    } catch {
      /* ignore */
    }
  }
}

function readStoredExecutionMode() {
  if (typeof window === 'undefined') return 'paper';
  const v = (window.localStorage.getItem('thiramai_execution_mode') || 'paper').toLowerCase();
  return v === 'live' ? 'live' : 'paper';
}

export default function AgentApprovalPanel({ osKey = 'stock', correlationStorageKey = 'thiramai_agent_correlation_id' }) {
  const [command, setCommand] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [plan, setPlan] = useState(null);
  const [approveSlider, setApproveSlider] = useState(0);
  const [executionMode, setExecutionMode] = useState(readStoredExecutionMode);
  const logsEndRef = useRef(null);

  const refreshPlan = useCallback(async (taskId) => agentApi.getPlan(taskId), []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [plan?.execution_logs]);

  useEffect(() => {
    if (!plan?.task_id) return undefined;
    const tick = async () => {
      try {
        const next = await refreshPlan(plan.task_id);
        if (next?.task_id) setPlan(next);
      } catch {
        /* offline */
      }
    };
    const id = setInterval(tick, plan?.requires_approval ? 900 : 1400);
    return () => clearInterval(id);
  }, [plan?.task_id, plan?.requires_approval, refreshPlan]);

  useEffect(() => {
    if (plan?.execution_mode === 'live' || plan?.execution_mode === 'paper') {
      setExecutionMode(plan.execution_mode);
      try {
        window.localStorage.setItem('thiramai_execution_mode', plan.execution_mode);
      } catch {
        /* ignore */
      }
    }
  }, [plan?.execution_mode]);

  const setMode = (mode) => {
    const m = mode === 'live' ? 'live' : 'paper';
    setExecutionMode(m);
    try {
      window.localStorage.setItem('thiramai_execution_mode', m);
    } catch {
      /* ignore */
    }
  };

  const submitCommand = async () => {
    setLoading(true);
    setError(null);
    try {
      if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {});
      }
      const corr = ensureAgentCorrelationId(correlationStorageKey);
      const data = await agentApi.command(command.trim(), osKey, executionMode, corr);
      setPlan(data);
      setApproveSlider(0);
      if (data.requires_approval) {
        notifyPendingApproval(data.task_id, data.title);
      }
    } catch (e) {
      setError(e.message || String(e));
      setPlan(null);
    } finally {
      setLoading(false);
    }
  };

  const approveStep = async (signal) => {
    if (!plan?.task_id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await agentApi.approve(plan.task_id, signal, executionMode);
      if (data.task_id) {
        setPlan(data);
        if (data.requires_approval) {
          notifyPendingApproval(data.task_id, data.title);
        }
      } else if (plan.task_id) {
        setPlan(await refreshPlan(plan.task_id));
      }
      setApproveSlider(0);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  const requiresApproval = plan?.requires_approval;
  const logs = Array.isArray(plan?.execution_logs) ? plan.execution_logs : [];
  const tp = plan?.trade_preview || null;
  const sent = tp?.market_sentiment;
  const score = typeof sent?.score === 'number' ? sent.score : null;
  const greeks = tp?.greeks;

  const onSwipeRelease = () => {
    if (approveSlider >= 92) {
      approveStep('success');
    }
    setApproveSlider(0);
  };

  return (
    <div style={{
      marginTop: 16,
      padding: 14,
      borderRadius: 12,
      border: '1px solid var(--color-border-tertiary, #333)',
      background: 'var(--color-background-secondary, #151515)',
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--color-text-primary, #eee)' }}>
        Jarvis · Plan → Approve → Execute ({osKey === 'research' ? 'Research OS' : 'Stock OS'})
      </div>
      <div style={{ marginBottom: 12, display: 'flex', gap: 10, alignItems: 'stretch', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={() => setMode('paper')}
          style={{
            flex: '1 1 140px',
            padding: '14px 16px',
            borderRadius: 12,
            border: executionMode === 'paper' ? '3px solid #378ADD' : '2px solid #444',
            background: executionMode === 'paper' ? '#378ADD22' : '#1a1a1a',
            color: '#e8e8e8',
            fontWeight: 700,
            fontSize: 14,
            cursor: 'pointer',
          }}
        >
          PAPER MODE
          <div style={{ fontSize: 10, fontWeight: 400, marginTop: 4, opacity: 0.85 }}>
            Internal simulation / portfolio
          </div>
        </button>
        <button
          type="button"
          onClick={() => setMode('live')}
          style={{
            flex: '1 1 140px',
            padding: '14px 16px',
            borderRadius: 12,
            border: executionMode === 'live' ? '3px solid #E24B4A' : '2px solid #444',
            background: executionMode === 'live' ? '#E24B4A22' : '#1a1a1a',
            color: '#ffdede',
            fontWeight: 700,
            fontSize: 14,
            cursor: 'pointer',
          }}
        >
          LIVE MODE
          <div style={{ fontSize: 10, fontWeight: 400, marginTop: 4, opacity: 0.85 }}>
            Broker SDK — risks real capital if keys valid
          </div>
        </button>
      </div>
      {plan?.trade_kill_switch_active && (
        <div style={{
          marginBottom: 10,
          padding: 10,
          borderRadius: 8,
          background: '#3d1515',
          border: '1px solid #a03030',
          fontSize: 12,
          color: '#ffb4b4',
        }}>
          Daily loss limit active — agent trade steps are blocked until next IST session.
        </div>
      )}
      <textarea
        value={command}
        onChange={(e) => setCommand(e.target.value)}
        placeholder="e.g. Run Nifty option chain analysis then analyze RELIANCE intraday"
        rows={3}
        style={{
          width: '100%',
          boxSizing: 'border-box',
          fontSize: 12,
          padding: 8,
          borderRadius: 8,
          border: '1px solid var(--color-border-tertiary, #444)',
          background: 'var(--color-background-primary, #0d0d0d)',
          color: 'var(--color-text-primary, #fff)',
          fontFamily: 'inherit',
        }}
      />
      <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={submitCommand}
          disabled={loading || !command.trim()}
          style={{
            padding: '8px 14px',
            borderRadius: 8,
            border: 'none',
            cursor: loading ? 'wait' : 'pointer',
            background: '#BA7517',
            color: '#fff',
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          {loading ? 'Planning…' : 'Generate plan'}
        </button>
        {error && (
          <span style={{ fontSize: 11, color: '#E24B4A' }}>{error}</span>
        )}
      </div>

      {plan?.steps && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary, #888)', marginBottom: 6 }}>
            Task: {plan.title} · id: <code style={{ fontSize: 10 }}>{plan.task_id}</code>
            {typeof plan.current_step_index === 'number' && (
              <span style={{ marginLeft: 8 }}>· cursor: {plan.current_step_index}</span>
            )}
          </div>
          <ol style={{ paddingLeft: 18, margin: 0 }}>
            {plan.steps.map((s) => (
              <li key={s.step} style={{ fontSize: 12, marginBottom: 6, color: 'var(--color-text-primary, #ddd)' }}>
                <strong>{s.action}</strong> — {s.description}
                <span style={{
                  marginLeft: 8,
                  fontSize: 10,
                  padding: '2px 6px',
                  borderRadius: 6,
                  background: s.status === 'pending_approval' ? '#7a3e8a80' : '#333',
                }}>
                  {s.status}
                </span>
              </li>
            ))}
          </ol>

          {tp && requiresApproval && (
            <div style={{
              marginTop: 14,
              padding: 12,
              borderRadius: 10,
              border: '1px solid #3d5a4a',
              background: '#0f1412',
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 10, color: '#9ae6b4' }}>
                Plan details (next trade step)
              </div>
              {sent && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, color: '#aaa', marginBottom: 4 }}>Market sentiment (last ~2h)</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{
                      fontSize: 20,
                      fontWeight: 700,
                      color: score == null ? '#888' : score >= 0.15 ? '#38a169' : score <= -0.15 ? '#e53e3e' : '#d69e2e',
                    }}>
                      {score != null ? score.toFixed(2) : '—'}
                    </span>
                    <span style={{ fontSize: 11, color: '#ccc' }}>{sent.label || 'neutral'}</span>
                  </div>
                  {sent.summary && (
                    <p style={{ fontSize: 11, color: '#a0aec0', margin: '6px 0 0 0', lineHeight: 1.4 }}>
                      {sent.summary}
                    </p>
                  )}
                </div>
              )}
              {greeks ? (
                <div>
                  <div style={{ fontSize: 11, color: '#aaa', marginBottom: 6 }}>Option Greeks (Black–Scholes)</div>
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
                    gap: 8,
                    fontSize: 11,
                    color: '#e2e8f0',
                  }}>
                    <div style={{ background: '#1a202c', padding: 8, borderRadius: 6 }}>
                      <div style={{ color: '#718096' }}>Delta</div>
                      <div style={{ fontWeight: 600 }}>{greeks.delta}</div>
                    </div>
                    <div style={{ background: '#1a202c', padding: 8, borderRadius: 6 }}>
                      <div style={{ color: '#718096' }}>Gamma</div>
                      <div style={{ fontWeight: 600 }}>{greeks.gamma}</div>
                    </div>
                    <div style={{ background: '#1a202c', padding: 8, borderRadius: 6 }}>
                      <div style={{ color: '#718096' }}>Theta / day</div>
                      <div style={{ fontWeight: 600 }}>{greeks.theta_per_day}</div>
                    </div>
                    <div style={{ background: '#1a202c', padding: 8, borderRadius: 6 }}>
                      <div style={{ color: '#718096' }}>Vega / 1% IV</div>
                      <div style={{ fontWeight: 600 }}>{greeks.vega_per_1pct_iv}</div>
                    </div>
                  </div>
                  {tp.option_hint && (
                    <div style={{ fontSize: 10, color: '#718096', marginTop: 8 }}>
                      Strike {tp.option_hint.strike} {tp.option_hint.right} · prem ₹{tp.option_hint.premium_inr_per_share}
                      {' · '}DTE ~{tp.option_hint.days_to_expiry}d · IV ~{(greeks.iv * 100).toFixed(1)}%
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: '#718096' }}>
                  Greeks apply to index option steps only (Nifty / Bank Nifty chain context).
                </div>
              )}
            </div>
          )}

          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--color-text-primary, #ccc)' }}>
              Live logs
            </div>
            <div
              style={{
                fontFamily: 'ui-monospace, monospace',
                fontSize: 11,
                lineHeight: 1.45,
                maxHeight: 180,
                overflowY: 'auto',
                padding: 10,
                borderRadius: 8,
                background: '#0a0a0a',
                border: '1px solid #2a2a2a',
                color: '#b8d4b8',
              }}
            >
              {logs.length === 0 ? (
                <span style={{ color: '#666' }}>No activity yet.</span>
              ) : (
                logs.map((line, i) => (
                  <div key={`${line.ts}-${i}`}>
                    <span style={{ color: '#666' }}>{line.ts ? `${line.ts} ` : ''}</span>
                    {line.message}
                  </div>
                ))
              )}
              <div ref={logsEndRef} />
            </div>
          </div>

          {requiresApproval && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, color: '#f0c674', marginBottom: 6 }}>Requires approval</div>
              <button
                type="button"
                onClick={() => approveStep('success')}
                disabled={loading}
                style={{
                  padding: '10px 18px',
                  borderRadius: 10,
                  border: 'none',
                  cursor: loading ? 'wait' : 'pointer',
                  background: '#1D9E75',
                  color: '#fff',
                  fontSize: 13,
                  fontWeight: 600,
                  width: '100%',
                  maxWidth: 360,
                }}
              >
                Click to execute next step
              </button>
              <div style={{ marginTop: 12, maxWidth: 360 }}>
                <div style={{ fontSize: 10, color: '#888', marginBottom: 4 }}>Swipe to approve</div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={approveSlider}
                  onChange={(e) => setApproveSlider(Number(e.target.value))}
                  onMouseUp={onSwipeRelease}
                  onTouchEnd={onSwipeRelease}
                  style={{ width: '100%' }}
                />
              </div>
              <button
                type="button"
                onClick={() => approveStep('reject')}
                disabled={loading}
                style={{
                  marginTop: 10,
                  padding: '6px 12px',
                  borderRadius: 8,
                  border: '1px solid #555',
                  background: 'transparent',
                  color: '#ccc',
                  fontSize: 11,
                  cursor: loading ? 'wait' : 'pointer',
                }}
              >
                Reject remaining steps
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
