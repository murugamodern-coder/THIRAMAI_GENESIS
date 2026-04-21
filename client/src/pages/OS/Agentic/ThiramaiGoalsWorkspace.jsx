import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { autonomyThiramaiApi } from '../../../services/api';
import {
  GOAL_EXAMPLES,
  GOAL_MIN_CHARS,
  GOAL_MIN_WORDS,
  GOAL_SUGGESTIONS,
  GOAL_TEMPLATES,
  validateGoalText,
} from '../../../config/goal-templates';
import { friendlyApiError } from '../../../utils/errorMessages';
import { getJobFeedback, setJobFeedback } from '../../../utils/jobFeedbackStorage';
import { loadOnboarding, saveOnboarding } from '../../../utils/onboardingStorage';

function fmtTs(unixSec) {
  if (unixSec == null || unixSec === '') return '—';
  try {
    return new Date(Number(unixSec) * 1000).toLocaleString();
  } catch {
    return String(unixSec);
  }
}

function stepOutcome(rec) {
  const rev = rec?.review?.status ?? rec?.review ?? '';
  const s = String(rev).toLowerCase();
  if (s === 'pass' || s === 'success' || s === 'ok') return 'success';
  if (s === 'fail' || s === 'failed' || s === 'error') return 'failure';
  return 'pending';
}

function tryNotify(title, body) {
  if (typeof Notification === 'undefined') return;
  if (Notification.permission !== 'granted') return;
  try {
    new Notification(title, { body: String(body || '').slice(0, 220) });
  } catch {
    /* ignore */
  }
}

function FriendlyErrorBox({ error }) {
  if (!error) return null;
  const f = typeof error === 'string' ? { title: 'Error', detail: error, suggestion: '' } : friendlyApiError(error);
  return (
    <div
      role="alert"
      style={{
        marginTop: 10,
        padding: '10px 12px',
        borderRadius: 8,
        border: '1px solid #c77',
        background: 'rgba(180, 60, 60, 0.08)',
        fontSize: 12,
        color: 'var(--color-text-primary)',
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{f.title}</div>
      <div style={{ opacity: 0.9, marginBottom: f.suggestion ? 6 : 0 }}>{f.detail}</div>
      {f.suggestion ? (
        <div style={{ color: 'var(--color-text-tertiary)' }}>
          <strong>Suggested next step:</strong> {f.suggestion}
        </div>
      ) : null}
    </div>
  );
}

function TimelineRail({ detail }) {
  const st = detail?.status || 'pending';
  const phases = [
    { key: 'pending', label: 'Pending', ts: detail?.created_ts, active: ['pending', 'queued'].includes(st) },
    {
      key: 'running',
      label: 'Running',
      ts: detail?.started_ts,
      active: st === 'running',
    },
    {
      key: 'done',
      label: st === 'failed' ? 'Failed' : 'Completed',
      ts: detail?.finished_ts,
      active: st === 'completed' || st === 'failed',
    },
  ];
  return (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, marginTop: 12, marginBottom: 8 }}>
      {phases.map((p, i) => (
        <React.Fragment key={p.key}>
          <div style={{ flex: 1, textAlign: 'center' }}>
            <div
              style={{
                width: 14,
                height: 14,
                borderRadius: '50%',
                margin: '0 auto 6px',
                background: p.active ? '#993556' : 'var(--color-border-tertiary)',
                boxShadow: p.active ? '0 0 0 3px rgba(153,53,86,0.25)' : 'none',
              }}
            />
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-primary)' }}>{p.label}</div>
            <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>{fmtTs(p.ts)}</div>
          </div>
          {i < phases.length - 1 ? (
            <div
              style={{
                alignSelf: 'center',
                flex: '0 0 24px',
                height: 2,
                background: 'var(--color-border-tertiary)',
                opacity: 0.7,
              }}
            />
          ) : null}
        </React.Fragment>
      ))}
    </div>
  );
}

export default function ThiramaiGoalsWorkspace() {
  const [goalText, setGoalText] = useState(GOAL_TEMPLATES[0]?.text || '');
  const [jobId, setJobId] = useState('');
  const [statusLine, setStatusLine] = useState('');
  const [detail, setDetail] = useState(null);
  const [logs, setLogs] = useState([]);
  const [history, setHistory] = useState([]);
  const [queue, setQueue] = useState(null);
  const [workers, setWorkers] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [metricsNote, setMetricsNote] = useState('');
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [rejectDraft, setRejectDraft] = useState({});
  const [expanded, setExpanded] = useState({});
  const [submitErr, setSubmitErr] = useState(null);
  const [pollErr, setPollErr] = useState(null);
  const [obsErr, setObsErr] = useState(null);
  const [onboarding, setOnboarding] = useState(() => loadOnboarding());
  const [feedbackRating, setFeedbackRating] = useState(null);
  const [feedbackComment, setFeedbackComment] = useState('');
  const timerRef = useRef(null);
  const obsTimerRef = useRef(null);
  const prevStatusRef = useRef({});
  const prevApprovalCountRef = useRef(null);
  const goalListId = useRef(`goal-datalist-${Math.random().toString(36).slice(2, 9)}`);

  const failureRate = useMemo(() => {
    const jobs = history || [];
    if (!jobs.length) return null;
    const failed = jobs.filter((j) => j.status === 'failed').length;
    return Math.round((failed / jobs.length) * 1000) / 10;
  }, [history]);

  const slowJobs = useMemo(() => (history || []).filter((j) => j.slow_job).slice(0, 8), [history]);

  const refreshHistory = useCallback(async () => {
    try {
      const h = await autonomyThiramaiApi.getHistory(40);
      setHistory(h.jobs || []);
    } catch (e) {
      setHistory([]);
    }
  }, []);

  const refreshObservability = useCallback(async () => {
    setObsErr(null);
    try {
      const [q, w, m] = await Promise.all([
        autonomyThiramaiApi.getQueue().catch(() => null),
        autonomyThiramaiApi.getWorkers().catch(() => null),
        autonomyThiramaiApi.internalMetrics().catch((e) => ({ _err: e })),
      ]);
      if (q && q.ok) setQueue(q);
      if (w && w.ok) setWorkers(w);
      if (m && m._err) {
        setMetrics(null);
        setMetricsNote(
          m._err.status === 403
            ? 'Extended metrics require an admin session. Queue and workers above are still available.'
            : '',
        );
      } else if (m && m.ok) {
        setMetrics(m);
        setMetricsNote('');
      }
    } catch (e) {
      setObsErr(e);
    }
  }, []);

  const refreshApprovals = useCallback(async () => {
    try {
      const a = await autonomyThiramaiApi.listApprovals();
      const list = a.pending || [];
      const prev = prevApprovalCountRef.current;
      if (prev !== null && list.length > prev && typeof Notification !== 'undefined') {
        tryNotify('Approval needed', `There are ${list.length} high-risk task(s) waiting for approval.`);
      }
      prevApprovalCountRef.current = list.length;
      setPendingApprovals(list);
    } catch {
      setPendingApprovals([]);
    }
  }, []);

  useEffect(() => {
    refreshHistory();
    refreshObservability();
    refreshApprovals();
    obsTimerRef.current = setInterval(() => {
      refreshObservability();
      refreshApprovals();
      refreshHistory();
    }, 8000);
    return () => {
      if (obsTimerRef.current) clearInterval(obsTimerRef.current);
    };
  }, [refreshHistory, refreshObservability, refreshApprovals]);

  const loadLogs = useCallback(async (id) => {
    if (!id) return;
    try {
      const L = await autonomyThiramaiApi.getLogs(id, 220);
      setLogs(L.logs || []);
    } catch {
      setLogs([]);
    }
  }, []);

  const pollOnce = useCallback(
    async (id) => {
      try {
        const s = await autonomyThiramaiApi.getStatus(id);
        setDetail(s);
        setPollErr(null);
        const disp = s.status || '';
        setStatusLine(`${disp} · ok=${String(s.ok)} · clean=${String(s.clean_cycle)}`);
        const prev = prevStatusRef.current[id];
        prevStatusRef.current[id] = disp;
        if (
          prev &&
          prev !== disp &&
          (disp === 'completed' || disp === 'failed') &&
          (prev === 'running' || prev === 'pending')
        ) {
          if (disp === 'completed') {
            tryNotify('Goal completed', s.goal || 'Your autonomous goal finished.');
          } else {
            tryNotify('Goal failed', String(s.error || 'The run ended with failures.'));
          }
        }
        await loadLogs(id);
        if (disp === 'completed' || disp === 'failed') {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
          refreshHistory();
          saveOnboarding({ resultsSeen: true });
          setOnboarding(loadOnboarding());
        }
      } catch (e) {
        setPollErr(e);
        setStatusLine('');
      }
    },
    [loadLogs, refreshHistory],
  );

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!jobId) return;
    const stored = getJobFeedback(jobId);
    setFeedbackRating(stored?.rating ?? null);
    setFeedbackComment(stored?.comment ?? '');
  }, [jobId]);

  const submitGoal = async () => {
    setSubmitErr(null);
    const v = validateGoalText(goalText);
    if (!v.ok) {
      setSubmitErr(new Error(v.message));
      return;
    }
    try {
      const res = await autonomyThiramaiApi.submitGoal(v.goal, null);
      setJobId(res.job_id);
      setStatusLine('queued…');
      setDetail(null);
      setLogs([]);
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = setInterval(() => pollOnce(res.job_id), 3000);
      pollOnce(res.job_id);
      refreshHistory();
      saveOnboarding({ firstGoalDone: true });
      setOnboarding(loadOnboarding());
    } catch (e) {
      setSubmitErr(e);
    }
  };

  const selectJob = async (id) => {
    setSubmitErr(null);
    setPollErr(null);
    setJobId(id);
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    await pollOnce(id);
    const st = prevStatusRef.current[id];
    if (st !== 'completed' && st !== 'failed') {
      timerRef.current = setInterval(() => pollOnce(id), 3000);
    }
    saveOnboarding({ resultsSeen: true });
    setOnboarding(loadOnboarding());
  };

  const replayFromHistory = async (id) => {
    setSubmitErr(null);
    try {
      const res = await autonomyThiramaiApi.replayJob(id);
      if (res.job_id) await selectJob(res.job_id);
    } catch (e) {
      setSubmitErr(e);
    }
  };

  const approveOne = async (approvalId) => {
    setSubmitErr(null);
    try {
      await autonomyThiramaiApi.approve(approvalId);
      await refreshApprovals();
    } catch (e) {
      setSubmitErr(e);
    }
  };

  const rejectOne = async (approvalId) => {
    setSubmitErr(null);
    const reason = (rejectDraft[approvalId] || '').trim();
    try {
      await autonomyThiramaiApi.reject(approvalId, reason);
      setRejectDraft((d) => ({ ...d, [approvalId]: '' }));
      await refreshApprovals();
    } catch (e) {
      setSubmitErr(e);
    }
  };

  const requestNotifications = () => {
    if (typeof Notification === 'undefined') return;
    Notification.requestPermission().then(() => {
      setOnboarding({ ...loadOnboarding() });
    });
  };

  const dismissOnboarding = () => {
    const o = saveOnboarding({ dismissed: true });
    setOnboarding(o);
  };

  const markDashboardSeen = () => {
    const o = saveOnboarding({ dashboardSeen: true });
    setOnboarding(o);
  };

  const latestResults = detail?.latest_results || [];
  const failures = detail?.failures || [];

  const qDepth = queue ? (queue.pending || []).length : 0;
  const activeRun = queue ? (queue.running || []).length : 0;
  const workerRows = workers?.workers || [];
  const healthyWorkers = workerRows.filter((w) => w.health !== 'dead').length;

  return (
    <div
      style={{
        background: 'var(--color-background-secondary)',
        borderRadius: 8,
        border: '1px solid var(--color-border-tertiary)',
        padding: 16,
        marginBottom: 24,
      }}
    >
      <div style={{ fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 8 }}>THIRAMAI goals</div>
      <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 10 }}>
        Product experience for autonomous runs. Point <code style={{ fontSize: 11 }}>REACT_APP_API_URL</code> at your
        API origin (e.g. <code style={{ fontSize: 11 }}>http://localhost:8000</code>).
      </p>

      {!onboarding.dismissed ? (
        <div
          style={{
            marginBottom: 14,
            padding: '10px 12px',
            borderRadius: 8,
            border: '1px solid var(--color-border-tertiary)',
            background: 'var(--color-background-primary)',
            fontSize: 12,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Quick start</div>
          <ol style={{ margin: '0 0 8px 18px', padding: 0, color: 'var(--color-text-secondary)' }}>
            <li style={{ textDecoration: onboarding.firstGoalDone ? 'line-through' : 'none' }}>
              Try your first goal — pick a template or example, then run.
            </li>
            <li style={{ textDecoration: onboarding.resultsSeen ? 'line-through' : 'none' }}>
              View results — timeline, steps, and execution logs update as the job runs.
            </li>
            <li style={{ textDecoration: onboarding.dashboardSeen ? 'line-through' : 'none' }}>
              Skim the dashboard — queue depth, workers, and history below.
            </li>
          </ol>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              type="button"
              onClick={requestNotifications}
              style={{
                background: 'transparent',
                color: '#993556',
                border: '2px solid #993556',
                borderRadius: 8,
                padding: '6px 10px',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              Enable desktop notifications
            </button>
            <button
              type="button"
              onClick={markDashboardSeen}
              style={{
                background: '#993556',
                color: '#fff',
                borderRadius: 8,
                padding: '6px 10px',
                border: 'none',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              I’ve reviewed the dashboard
            </button>
            <button
              type="button"
              onClick={dismissOnboarding}
              style={{ background: 'transparent', border: 'none', color: 'var(--color-text-tertiary)', cursor: 'pointer', fontSize: 12 }}
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      <div style={{ marginBottom: 10, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
        Goals need at least {GOAL_MIN_WORDS} words and {GOAL_MIN_CHARS} characters so the planner has enough context.
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <label style={{ fontSize: 12, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
          Template
          <select
            value=""
            onChange={(e) => {
              const id = e.target.value;
              const t = GOAL_TEMPLATES.find((x) => x.id === id);
              if (t) setGoalText(t.text);
              e.target.value = '';
            }}
            style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-border-tertiary)' }}
          >
            <option value="">Choose…</option>
            {GOAL_TEMPLATES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        {GOAL_EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => setGoalText(ex)}
            style={{
              fontSize: 11,
              padding: '4px 8px',
              borderRadius: 999,
              border: '1px solid var(--color-border-tertiary)',
              background: 'var(--color-background-primary)',
              cursor: 'pointer',
              color: 'var(--color-text-secondary)',
            }}
          >
            {ex.length > 42 ? `${ex.slice(0, 40)}…` : ex}
          </button>
        ))}
      </div>

      <datalist id={goalListId.current}>
        {GOAL_SUGGESTIONS.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>

      <label style={{ display: 'block', fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 6 }}>
        Suggestions (autocomplete)
        <input
          list={goalListId.current}
          placeholder="Type to search, then pick a phrase to fill the goal below"
          onChange={(e) => {
            const v = e.target.value;
            if (v.trim()) setGoalText(v);
          }}
          style={{
            width: '100%',
            marginTop: 4,
            padding: 8,
            borderRadius: 6,
            border: '1px solid var(--color-border-tertiary)',
            fontFamily: 'inherit',
            fontSize: 13,
            boxSizing: 'border-box',
          }}
        />
      </label>

      <textarea
        value={goalText}
        onChange={(e) => setGoalText(e.target.value)}
        rows={4}
        placeholder="Describe what you want done — context, constraints, and the outcome you expect."
        style={{
          width: '100%',
          padding: 8,
          marginBottom: 8,
          borderRadius: 6,
          border: '1px solid var(--color-border-tertiary)',
          fontFamily: 'inherit',
          boxSizing: 'border-box',
        }}
      />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {GOAL_SUGGESTIONS.slice(0, 10).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setGoalText(s)}
            style={{
              fontSize: 10,
              padding: '4px 8px',
              borderRadius: 6,
              border: '1px solid var(--color-border-tertiary)',
              background: 'var(--color-background-primary)',
              cursor: 'pointer',
              color: 'var(--color-text-tertiary)',
              maxWidth: '100%',
              textAlign: 'left',
            }}
            title={s}
          >
            {s.length > 48 ? `${s.slice(0, 46)}…` : s}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={submitGoal}
          style={{
            background: '#993556',
            color: '#fff',
            borderRadius: 8,
            padding: '8px 14px',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          Run goal
        </button>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{statusLine}</span>
        {jobId ? (
          <span style={{ fontSize: 11, wordBreak: 'break-all', color: 'var(--color-text-secondary)' }}>
            job: {jobId}
          </span>
        ) : null}
      </div>
      <FriendlyErrorBox error={submitErr} />
      <FriendlyErrorBox error={pollErr} />

      {detail ? (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Execution timeline</div>
          <TimelineRail detail={detail} />
          {detail.slow_job ? (
            <div style={{ fontSize: 11, color: '#a65', marginBottom: 6 }}>
              Flagged as a slow job (took longer than the typical threshold).
            </div>
          ) : null}
        </div>
      ) : null}

      {detail ? (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Result summary</div>
          <div
            style={{
              padding: '10px 12px',
              borderRadius: 8,
              border: '1px solid var(--color-border-tertiary)',
              background: 'var(--color-background-primary)',
              fontSize: 12,
            }}
          >
            <div>
              <strong>Status:</strong> {detail.status}{' '}
              {detail.status === 'completed' ? (
                <span style={{ color: detail.ok ? '#2a8f2a' : '#b44' }}>{detail.ok ? '✓ success' : '✗ incomplete'}</span>
              ) : null}
              {detail.status === 'failed' ? <span style={{ color: '#b44' }}> ✗ failed</span> : null}
            </div>
            {detail.execution_ms != null ? (
              <div style={{ marginTop: 4 }}>
                <strong>Duration:</strong> {Math.round(Number(detail.execution_ms))} ms
              </div>
            ) : null}
            {detail.error ? (
              <div style={{ marginTop: 6, color: '#b44' }}>
                <strong>Error:</strong> {String(detail.error)}
              </div>
            ) : null}
            {detail.failure_analysis ? (
              <pre
                style={{
                  marginTop: 8,
                  fontSize: 11,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  color: 'var(--color-text-secondary)',
                }}
              >
                {typeof detail.failure_analysis === 'string'
                  ? detail.failure_analysis
                  : JSON.stringify(detail.failure_analysis, null, 2)}
              </pre>
            ) : null}
          </div>
        </div>
      ) : null}

      {latestResults.length ? (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Plan steps</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {latestResults.map((rec, idx) => {
              const oid = rec?.task_id ?? `step-${idx}`;
              const out = stepOutcome(rec);
              const open = !!expanded[idx];
              return (
                <div
                  key={oid}
                  style={{
                    border: '1px solid var(--color-border-tertiary)',
                    borderRadius: 8,
                    overflow: 'hidden',
                    background: 'var(--color-background-primary)',
                  }}
                >
                  <button
                    type="button"
                    onClick={() => setExpanded((e) => ({ ...e, [idx]: !open }))}
                    style={{
                      width: '100%',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '8px 10px',
                      border: 'none',
                      background: 'transparent',
                      cursor: 'pointer',
                      fontSize: 12,
                      textAlign: 'left',
                    }}
                  >
                    <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                      Step {idx + 1}: {String(rec?.type || rec?.task_type || 'task')}{' '}
                      <span style={{ fontWeight: 400, color: 'var(--color-text-tertiary)' }}>({oid})</span>
                    </span>
                    <span style={{ fontSize: 11 }}>
                      {out === 'success' ? <span style={{ color: '#2a8f2a' }}>● ok</span> : null}
                      {out === 'failure' ? <span style={{ color: '#b44' }}>● issue</span> : null}
                      {out === 'pending' ? <span style={{ color: '#888' }}>● pending</span> : null}
                      <span style={{ marginLeft: 8, color: 'var(--color-text-tertiary)' }}>{open ? '▼' : '▶'}</span>
                    </span>
                  </button>
                  {open ? (
                    <pre
                      style={{
                        margin: 0,
                        padding: '0 10px 10px',
                        fontSize: 11,
                        overflow: 'auto',
                        maxHeight: 220,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      }}
                    >
                      {JSON.stringify(rec, null, 2)}
                    </pre>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {failures.length ? (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: '#a44' }}>
            Retries / failures ({failures.length})
          </div>
          <ul style={{ fontSize: 11, margin: 0, paddingLeft: 18, color: 'var(--color-text-secondary)' }}>
            {failures.slice(-12).map((f, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                <code>{typeof f === 'string' ? f : JSON.stringify(f)}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {jobId ? (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Execution log</div>
          <pre
            style={{
              margin: 0,
              fontSize: 11,
              overflow: 'auto',
              maxHeight: 200,
              background: 'var(--color-background-primary)',
              padding: 8,
              borderRadius: 6,
              border: '1px solid var(--color-border-tertiary)',
            }}
          >
            {logs.length
              ? logs
                  .map((line) => {
                    const t = fmtTs(line.ts);
                    const lvl = line.level || '';
                    const msg = line.message || '';
                    const ex = line.extra ? ` ${JSON.stringify(line.extra)}` : '';
                    return `[${t}] ${lvl} ${msg}${ex}`;
                  })
                  .join('\n')
              : 'No log lines yet (they appear once execution starts).'}
          </pre>
        </div>
      ) : null}

      {jobId ? (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--color-border-tertiary)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>How was this result?</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => {
                setFeedbackRating('up');
                setJobFeedback(jobId, { rating: 'up', comment: feedbackComment });
              }}
              style={{
                padding: '6px 12px',
                borderRadius: 8,
                border: feedbackRating === 'up' ? '2px solid #2a8f2a' : '1px solid var(--color-border-tertiary)',
                background: 'var(--color-background-primary)',
                cursor: 'pointer',
              }}
            >
              👍 Good
            </button>
            <button
              type="button"
              onClick={() => {
                setFeedbackRating('down');
                setJobFeedback(jobId, { rating: 'down', comment: feedbackComment });
              }}
              style={{
                padding: '6px 12px',
                borderRadius: 8,
                border: feedbackRating === 'down' ? '2px solid #b44' : '1px solid var(--color-border-tertiary)',
                background: 'var(--color-background-primary)',
                cursor: 'pointer',
              }}
            >
              👎 Needs work
            </button>
            <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
              Saved locally in this browser to guide what you iterate on next.
            </span>
          </div>
          <textarea
            value={feedbackComment}
            onChange={(e) => {
              const v = e.target.value;
              setFeedbackComment(v);
              setJobFeedback(jobId, { rating: feedbackRating, comment: v });
            }}
            placeholder="Optional note — what should be different next time?"
            rows={2}
            style={{
              width: '100%',
              marginTop: 8,
              padding: 8,
              borderRadius: 6,
              border: '1px solid var(--color-border-tertiary)',
              fontFamily: 'inherit',
              fontSize: 12,
            }}
          />
        </div>
      ) : null}

      <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--color-border-tertiary)' }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Approvals</div>
        <p style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
          High-risk autonomous steps wait here. Approving continues execution; rejecting stops with a reason.
        </p>
        {!pendingApprovals.length ? (
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>No pending approvals.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {pendingApprovals.map((row) => (
              <div
                key={row.approval_id}
                style={{
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: '1px solid var(--color-border-tertiary)',
                  background: 'var(--color-background-primary)',
                  fontSize: 12,
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Approval {row.approval_id?.slice(0, 12)}…</div>
                <div style={{ marginBottom: 4 }}>
                  <strong>Goal:</strong> {row.goal || '—'}
                </div>
                {row.task_summary ? (
                  <div style={{ marginBottom: 6, color: 'var(--color-text-secondary)' }}>
                    <strong>Task:</strong> {String(row.task_summary.description || row.task_summary.type || '—')}{' '}
                    {row.task_summary.risk_level != null ? (
                      <span style={{ color: '#a65' }}>· risk {String(row.task_summary.risk_level)}</span>
                    ) : null}
                    {row.task_summary.command ? (
                      <pre style={{ margin: '6px 0 0', fontSize: 10, whiteSpace: 'pre-wrap' }}>
                        {String(row.task_summary.command)}
                      </pre>
                    ) : null}
                  </div>
                ) : null}
                <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
                  Requested {fmtTs(row.created_ts)}
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                  <button
                    type="button"
                    onClick={() => approveOne(row.approval_id)}
                    style={{
                      background: '#2a6b2a',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 8,
                      padding: '6px 12px',
                      cursor: 'pointer',
                      fontSize: 12,
                    }}
                  >
                    Approve
                  </button>
                  <input
                    type="text"
                    placeholder="Reject reason (shown to the system)"
                    value={rejectDraft[row.approval_id] || ''}
                    onChange={(e) =>
                      setRejectDraft((d) => ({
                        ...d,
                        [row.approval_id]: e.target.value,
                      }))
                    }
                    style={{
                      flex: '1 1 200px',
                      padding: '6px 8px',
                      borderRadius: 6,
                      border: '1px solid var(--color-border-tertiary)',
                      fontSize: 12,
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => rejectOne(row.approval_id)}
                    style={{
                      background: '#a33',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 8,
                      padding: '6px 12px',
                      cursor: 'pointer',
                      fontSize: 12,
                    }}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Observability</div>
        <FriendlyErrorBox error={obsErr} />
        {metricsNote ? (
          <p style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>{metricsNote}</p>
        ) : null}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
          <div style={metricCardStyle}>
            <div style={metricValueStyle}>{qDepth}</div>
            <div style={metricLabelStyle}>Queue depth (pending)</div>
          </div>
          <div style={metricCardStyle}>
            <div style={metricValueStyle}>{activeRun}</div>
            <div style={metricLabelStyle}>Running now</div>
          </div>
          <div style={metricCardStyle}>
            <div style={metricValueStyle}>{workerRows.length}</div>
            <div style={metricLabelStyle}>Workers seen</div>
          </div>
          <div style={metricCardStyle}>
            <div style={metricValueStyle}>{healthyWorkers}</div>
            <div style={metricLabelStyle}>Workers healthy</div>
          </div>
          <div style={metricCardStyle}>
            <div style={metricValueStyle}>{failureRate != null ? `${failureRate}%` : '—'}</div>
            <div style={metricLabelStyle}>Recent failure rate (history)</div>
          </div>
          {metrics?.performance?.goal_success_rate != null ? (
            <div style={metricCardStyle}>
              <div style={metricValueStyle}>
                {String(metrics.performance.goal_success_rate).slice(0, 12)}
              </div>
              <div style={metricLabelStyle}>Goal success (admin metric)</div>
            </div>
          ) : null}
        </div>

        {workerRows.length ? (
          <div style={{ marginBottom: 10, fontSize: 12 }}>
            <strong>Workers:</strong>{' '}
            {workerRows.map((w) => (
              <span
                key={w.worker_id}
                style={{
                  display: 'inline-block',
                  marginRight: 8,
                  marginBottom: 4,
                  padding: '2px 8px',
                  borderRadius: 6,
                  border: '1px solid var(--color-border-tertiary)',
                  fontSize: 11,
                }}
              >
                {w.worker_id?.slice(0, 10)}… · {w.health}
                {w.age_sec != null ? ` · ${w.age_sec}s ago` : ''}
              </span>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
            No worker heartbeats recorded yet (workers appear when distributed execution is enabled).
          </p>
        )}

        {slowJobs.length ? (
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Slow jobs (recent)</div>
            <ul style={{ fontSize: 11, margin: 0, paddingLeft: 18 }}>
              {slowJobs.map((j) => (
                <li key={j.id} style={{ marginBottom: 4 }}>
                  <button
                    type="button"
                    onClick={() => selectJob(j.id)}
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: 0,
                      color: '#993556',
                      cursor: 'pointer',
                      textDecoration: 'underline',
                      fontSize: 11,
                    }}
                  >
                    {j.id?.slice(0, 10)}…
                  </button>{' '}
                  · {(j.goal || '').slice(0, 70)}
                  {(j.goal || '').length > 70 ? '…' : ''}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      <div style={{ marginTop: 14, fontSize: 13, fontWeight: 600 }}>Recent jobs</div>
      <ul style={{ paddingLeft: 18, marginTop: 8, fontSize: 12 }}>
        {history.map((j) => (
          <li key={j.id} style={{ marginBottom: 6 }}>
            <button
              type="button"
              onClick={() => selectJob(j.id)}
              style={{
                background: 'none',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
                color: '#993556',
                fontWeight: j.id === jobId ? 700 : 400,
                textDecoration: 'underline',
              }}
            >
              {j.status}
            </button>
            {' — '}
            <span style={{ color: 'var(--color-text-secondary)' }}>{(j.goal || '').slice(0, 80)}</span>
            {(j.goal || '').length > 80 ? '…' : ''}
            <button
              type="button"
              onClick={() => replayFromHistory(j.id)}
              style={{
                marginLeft: 8,
                fontSize: 11,
                background: 'transparent',
                border: '1px solid var(--color-border-tertiary)',
                borderRadius: 6,
                padding: '2px 6px',
                cursor: 'pointer',
              }}
            >
              Replay
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

const metricCardStyle = {
  background: 'var(--color-background-primary)',
  borderRadius: 8,
  padding: '10px 12px',
  border: '1px solid var(--color-border-tertiary)',
  minWidth: 120,
  flex: '1 1 120px',
};

const metricValueStyle = {
  fontSize: 18,
  fontWeight: 600,
  color: 'var(--color-text-primary)',
};

const metricLabelStyle = {
  fontSize: 11,
  color: 'var(--color-text-tertiary)',
};
