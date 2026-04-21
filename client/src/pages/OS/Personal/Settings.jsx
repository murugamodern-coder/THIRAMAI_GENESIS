import React, { useState } from 'react';

export default function PersonalSettings() {
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('');

  const handleSave = () => {
    // Handle save logic
  };

  const testConnection = () => {
    fetch('/api/os/personal/tasks')
      .then(res => res.json())
      .then(data => {
        if (data.connected) {
          setConnectionStatus('Connected successfully to Lindy.ai');
        } else {
          setConnectionStatus('Failed to connect to Lindy.ai');
        }
      });
  };

  return (
    <div style={{ padding: 20 }}>
      <h2>Personal OS Settings</h2>
      <div style={{ marginBottom: 20 }}>
        <label>Lindy.ai API Key</label>
        <div style={{ position: 'relative', marginBottom: 12 }}>
          <input
            type={showKey ? 'text' : 'password'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            style={{ width: '100%', padding: 8, boxSizing: 'border-box' }}
          />
          <button onClick={() => setShowKey(!showKey)}
            style={{ position: 'absolute', right: 10, top: 10 }}>
            {showKey ? 'Hide' : 'Show'}
          </button>
        </div>
        <button onClick={handleSave} style={{ marginRight: 20 }}>Save</button>
        <button onClick={testConnection}>Test Connection</button>
      </div>
      <div>
        {connectionStatus && <p>{connectionStatus}</p>}
      </div>
    </div>
  );
}
