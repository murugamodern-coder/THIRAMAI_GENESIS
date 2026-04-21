import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

function KPICard({ label, value }) {
  return (
    <div
      style={{
        background: 'var(--color-background-secondary)',
        borderRadius: 8,
        padding: '10px',
        border: '1px solid var(--color-border-tertiary)',
        marginBottom: 12,
      }}
    >
      <div style={{ fontSize: 16, fontWeight: 500, color: 'var(--color-text-primary)' }}>{value}</div>
      <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{label}</div>
    </div>
  );
}

function PLTable({ orgId = null }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const [rows, setRows] = useState([]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(false);
        // Placeholder until Business OS ledger API is wired here
        await new Promise((resolve) => setTimeout(resolve, 80));
        if (!cancelled) {
          setRows([]);
          setLoading(false);
        }
      } catch (_e) {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [orgId, retryToken]);

  const handleRetry = () => {
    setRetryToken((t) => t + 1);
  };

  const safeRows = Array.isArray(rows) ? rows : [];

  return (
    <div style={{ paddingRight: 12 }}>
      <h3 style={{ color: 'var(--color-text-primary)' }}>P&amp;L Table</h3>
      {loading ? <div>Loading…</div> : null}
      {error ? (
        <button type="button" onClick={handleRetry} style={{ marginBottom: 12 }}>
          Data unavailable — retry
        </button>
      ) : null}
      {!loading && !error ? (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th>Category</th>
              <th>Today</th>
              <th>This Month</th>
              <th>Last Month</th>
            </tr>
          </thead>
          <tbody>
            {safeRows.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ padding: '12px 0', color: 'var(--color-text-tertiary)' }}>
                  No data yet. Connect your ledger when available.
                </td>
              </tr>
            ) : (
              safeRows.map((row, idx) => (
                <tr key={row?.id ?? idx}>
                  <td>{row?.category ?? '—'}</td>
                  <td>{row?.today ?? '—'}</td>
                  <td>{row?.month ?? '—'}</td>
                  <td>{row?.lastMonth ?? '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

function QuickActions() {
  const navigate = useNavigate();
  return (
    <div style={{ paddingLeft: 12 }}>
      <h3 style={{ color: 'var(--color-text-primary)' }}>Quick Actions</h3>
      <button type="button" style={actionButtonStyle} onClick={() => navigate('/bills/new?type=cash')}>
        New cash bill
      </button>
      <button type="button" style={actionButtonStyle} onClick={() => navigate('/bills/new?type=gst')}>
        New GST invoice
      </button>
      <button type="button" style={actionButtonStyle} onClick={() => navigate('/spend/new')}>
        Record expense
      </button>
      <button type="button" style={actionButtonStyle} onClick={() => navigate('/stock/new')}>
        Add stock entry
      </button>
      <button type="button" style={actionButtonStyle} onClick={() => navigate('/gst')}>
        File GST return
      </button>
    </div>
  );
}

const actionButtonStyle = {
  background: '#378ADD',
  color: '#fff',
  borderRadius: 8,
  padding: '10px',
  marginBottom: 10,
  border: 'none',
  cursor: 'pointer',
  width: '100%',
};

export default function Business() {
  const [activeTab, setActiveTab] = useState('trading');
  const navigate = useNavigate();

  return (
    <div style={{ padding: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={{ color: 'var(--color-text-primary)' }}>Business OS</h1>
        <button
          type="button"
          onClick={() => navigate(-1)}
          style={{
            background: '#378ADD',
            color: '#fff',
            borderRadius: 8,
            padding: '6px 12px',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          Back
        </button>
        <select aria-label="Organization" defaultValue="">
          <option value="">Organization…</option>
        </select>
      </div>

      <div style={{ marginBottom: 24 }}>
        <button type="button" style={tabStyle(activeTab === 'trading')} onClick={() => setActiveTab('trading')}>
          Trading
        </button>
        <button
          type="button"
          style={tabStyle(activeTab === 'manufacturing')}
          onClick={() => setActiveTab('manufacturing')}
        >
          Manufacturing
        </button>
        <button type="button" style={tabStyle(activeTab === 'govschemes')} onClick={() => setActiveTab('govschemes')}>
          Gov Schemes
        </button>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <KPICard label="Revenue today" value="₹0" />
        <KPICard label="Expenses" value="₹0" />
        <KPICard label="Profit" value="₹0" />
        <KPICard label="Open invoices" value="0" />
        <KPICard label="GST due" value="₹0" />
      </div>

      {activeTab === 'trading' ? (
        <div style={{ display: 'flex', marginBottom: 24 }}>
          <PLTable orgId={null} />
          <QuickActions />
        </div>
      ) : null}

      {activeTab === 'manufacturing' ? <div>Coming soon — Phase 3</div> : null}

      {activeTab === 'govschemes' ? (
        <div>
          <p style={{ color: 'var(--color-text-tertiary)', fontSize: 14 }}>Subsidy tracking will appear here.</p>
        </div>
      ) : null}
    </div>
  );
}

const tabStyle = (active) => ({
  background: active ? '#ffffff' : '#f0f0f0',
  color: active ? '#000' : '#888',
  padding: '8px 16px',
  border: 'none',
  borderBottom: active ? '2px solid #378ADD' : '1px solid #ddd',
  cursor: 'pointer',
  marginRight: 4,
});
