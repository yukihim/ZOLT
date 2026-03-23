import React from 'react';

function ServerStatus({ health }) {
  // If backend is unreachable, show a placeholder
  if (!health) {
    return (
      <div className="glass-card" id="server-status-panel">
        <div className="card-header-custom">
          <span className="card-header-icon">🖥️</span>
          <h2>MCP Servers</h2>
        </div>
        <div className="server-list">
          <div className="server-item">
            <span className="status-dot offline" />
            <span className="server-name" style={{ color: 'var(--text-muted)' }}>
              Connecting to backend...
            </span>
          </div>
        </div>
      </div>
    );
  }

  // Known servers and their expected tools
  const knownServers = [
    {
      name: 'GitHub',
      key: 'github',
      icon: '🐙',
      description: 'Code search, issue triaging, commit analysis',
    },
    {
      name: 'Google Drive',
      key: 'gdrive',
      icon: '📁',
      description: 'Runbook retrieval, architecture docs',
    },
    {
      name: 'Local Metrics',
      key: 'metrics',
      icon: '📈',
      description: 'Server health, CPU, memory, uptime',
    },
  ];

  return (
    <div className="glass-card" id="server-status-panel">
      <div className="card-header-custom">
        <span className="card-header-icon">🖥️</span>
        <h2>MCP Servers</h2>
      </div>
      <div className="server-list">
        {knownServers.map((server) => {
          const isOnline = health.mcp_servers?.includes(server.key);
          return (
            <div className="server-item" key={server.key}>
              <span className={`status-dot ${isOnline ? 'online' : 'offline'}`} />
              <div style={{ flex: 1 }}>
                <div className="server-name">
                  {server.icon} {server.name}
                </div>
                <div
                  className="server-tools"
                  style={{ marginTop: '2px', fontSize: '0.72rem' }}
                >
                  {server.description}
                </div>
              </div>
              <span
                className="server-tools"
                style={{
                  color: isOnline ? 'var(--success)' : 'var(--text-muted)',
                  fontWeight: 500,
                }}
              >
                {isOnline ? 'ONLINE' : 'OFFLINE'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ServerStatus;
