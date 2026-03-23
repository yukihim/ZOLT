import React, { useState, useEffect } from 'react';
import ChatPanel from './components/ChatPanel';
import MetricsChart from './components/MetricsChart';
import ServerStatus from './components/ServerStatus';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function App() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`);
        setHealth(await res.json());
      } catch {
        setHealth({ status: 'unreachable', mcp_servers: [] });
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-container">
      {/* ── Header ─────────────────────────────────────── */}
      <header className="app-header d-flex align-items-center">
        <span className="app-logo">⚡ ZOLT</span>
        <span className="app-subtitle">Zero Overhead LLM Transport</span>
        <div className="ms-auto d-flex align-items-center gap-2">
          <span
            className={`status-dot ${health?.status === 'healthy' ? 'online' : 'offline'}`}
          />
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            {health?.status === 'healthy' ? 'System Online' : 'Connecting...'}
          </span>
        </div>
      </header>

      {/* ── Main Grid ──────────────────────────────────── */}
      <main className="main-grid">
        <ChatPanel apiBase={API_BASE} />
        <aside className="sidebar">
          <MetricsChart apiBase={API_BASE} />
          <ServerStatus health={health} />
        </aside>
      </main>
    </div>
  );
}

export default App;
