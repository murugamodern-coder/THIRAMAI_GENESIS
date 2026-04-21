import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function StockSettings() {
  const navigate = useNavigate();
  const [keys, setKeys] = useState({
    quiver_api_key: '', bloomberg_key: '', risk_alert_score: 70, refresh_seconds: 10
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    setSaving(true);
    await fetch('/api/os/stock/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(keys)
    });
    setSaving(false); setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div style={{ padding: '24px', maxWidth: 560 }}>
      <button onClick={() => navigate(-1)}
        style={{ background: 'none', border: 'none', cursor: 'pointer',
                 color: 'var(--color-text-secondary)', fontSize: 13,
                 marginBottom: 20, padding: 0 }}>
        ← Back to Stock OS
      </button>
      <h2 style={{ fontSize: 17, fontWeight: 500, marginBottom: 20,
                   color: 'var(--color-text-primary)' }}>Stock OS Settings</h2>

      {[
        { key: 'quiver_api_key', label: 'Quiver Quantitative API key', type: 'password' },
        { key: 'bloomberg_key', label: 'Bloomberg API key', type: 'password' },
      ].map(f => (
        <div key={f.key} style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, color: 'var(--color-text-secondary)',
                         display: 'block', marginBottom: 6 }}>{f.label}</label>
          <input type={f.type} value={keys[f.key]}
            onChange={e => setKeys(k => ({ ...k, [f.key]: e.target.value }))}
            style={{ width: '100%', padding: '8px 12px', borderRadius: 8,
                     border: '0.5px solid var(--color-border-secondary)',
                     background: 'var(--color-background-secondary)',
                     color: 'var(--color-text-primary)', fontSize: 13,
                     outline: 'none', fontFamily: 'inherit' }} />
        </div>
      ))}

      <button onClick={save} disabled={saving}
        style={{ padding: '8px 20px', borderRadius: 8, border: 'none',
                 background: '#BA7517', color: '#fff', cursor: 'pointer',
                 fontSize: 13, fontWeight: 500 }}>
        {saving ? 'Saving...' : saved ? 'Saved ✓' : 'Save settings'}
      </button>
    </div>
  );
}
