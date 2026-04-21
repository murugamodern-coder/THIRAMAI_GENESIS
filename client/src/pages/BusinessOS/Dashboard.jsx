import React, { useEffect, useState } from 'react';
import { LoadingSkeleton, EmptyState } from '../../components/LoadingSkeleton';

/** Fetches Business P&amp;L snapshot; exposes stable hook order + retry token. */
const usePL = (orgId) => {
  const [state, setState] = useState({ status: 'idle', data: null, error: null });
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    setState({ status: 'loading', data: null, error: null });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);

    fetch(`/api/business/${orgId}/pl/today`, { signal: controller.signal })
      .then((r) => r.json())
      .then((data) => setState({ status: 'ok', data, error: null }))
      .catch((err) => {
        if (err.name === 'AbortError') {
          setState({ status: 'error', data: null, error: 'Request timed out' });
        } else {
          setState({ status: 'error', data: null, error: err.message });
        }
      })
      .finally(() => clearTimeout(timeout));

    return () => {
      controller.abort();
      clearTimeout(timeout);
    };
  }, [orgId, retryToken]);

  const retry = () => setRetryToken((t) => t + 1);

  return { ...state, retry };
};

function PLTablePreview({ data }) {
  return (
    <div style={{ fontSize: 12, color: 'var(--color-text-primary)' }}>
      <pre style={{ overflow: 'auto', maxHeight: 320 }}>
        {data == null ? '—' : JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}

/** Not currently routed from App.jsx — keep hooks valid for future Business OS embedding. */
const BusinessDashboard = ({ orgId }) => {
  const pl = usePL(orgId);

  if (pl.status === 'loading') {
    return <LoadingSkeleton rows={3} />;
  }
  if (pl.status === 'error') {
    return (
      <EmptyState
        title="Could not load data"
        subtitle={pl.error}
        action={
          <button type="button" onClick={() => pl.retry()} style={{ cursor: 'pointer' }}>
            Retry
          </button>
        }
      />
    );
  }
  return <PLTablePreview data={pl.data} />;
};

export default BusinessDashboard;
