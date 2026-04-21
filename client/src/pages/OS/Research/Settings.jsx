import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function ResearchSettings() {
  const navigate = useNavigate();
  const [keys, setKeys] = useState({
    perplexity_key: '', openai_key: '', crewai_endpoint: '', max_search_depth: 5
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    setSaving(true);
    await fetch('/api/os/research/settings', {
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
      <button onClick={() => navigate('/os/research')}
        style={{ background: 'none', border: 'none', cursor: 'pointer',
                 color: 'var(--color-text-secondary)', fontSize: 13,
                 marginBottom: 20, padding: 0 }}>
        ← Back to Research OS
      </button>
      <h2 style={{ fontSize: 17, fontWeight: 500, marginBottom: 20,
                   color: 'var(--color-text-primary)' }}>Research OS Settings</h2>

      {[
        { key: 'perplexity_key', label: 'Perplexity API key', type: 'password' },
        { key: 'openai_key', label: 'OpenAI API key', type: 'password' },
        { key: 'crewai_endpoint', label: 'CrewAI endpoint URL', type: 'text' },
        { key: 'max_search_depth', label: 'Max search depth (1-10)', type: 'number' },
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
                 background: '#D85A30', color: '#fff', cursor: 'pointer',
                 fontSize: 13, fontWeight: 500 }}>
        {saving ? 'Saving...' : saved ? 'Saved ✓' : 'Save settings'}
      </button>
    </div>
  );
}
