import React, { useState, useEffect } from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Filler,
} from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler);

function MetricsChart({ apiBase }) {
  const [summary, setSummary] = useState(null);
  const [evals, setEvals] = useState([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [sumRes, evalsRes] = await Promise.all([
          fetch(`${apiBase}/api/evals/summary`),
          fetch(`${apiBase}/api/evals?limit=20`),
        ]);
        setSummary(await sumRes.json());
        setEvals(await evalsRes.json());
      } catch {
        // Backend unreachable — keep stale data
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [apiBase]);

  // Chart data: latency over recent turns
  const chartData = {
    labels: evals.map((e) => e.turn_id || '').reverse(),
    datasets: [
      {
        label: 'Latency (s)',
        data: evals.map((e) => e.latency_seconds).reverse(),
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99, 102, 241, 0.1)',
        fill: true,
        tension: 0.4,
        pointRadius: 3,
        pointBackgroundColor: '#8b5cf6',
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: {
        display: false,
      },
      y: {
        grid: { color: 'rgba(148,163,184,0.08)' },
        ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 } },
      },
    },
  };

  return (
    <div className="glass-card" id="metrics-panel">
      <div className="card-header-custom">
        <span className="card-header-icon">📊</span>
        <h2>Evaluation Metrics</h2>
      </div>

      {/* Summary tiles */}
      <div className="metrics-grid">
        <div className="metric-tile">
          <div className="metric-label">Total Turns</div>
          <div className="metric-value">{summary?.total_turns ?? '—'}</div>
        </div>
        <div className="metric-tile">
          <div className="metric-label">Avg Latency</div>
          <div className="metric-value">
            {summary?.avg_latency != null ? `${summary.avg_latency.toFixed(2)}s` : '—'}
          </div>
        </div>
        <div className="metric-tile">
          <div className="metric-label">Avg TSR</div>
          <div className="metric-value">
            {summary?.avg_tsr != null ? `${(summary.avg_tsr * 100).toFixed(0)}%` : '—'}
          </div>
        </div>
        <div className="metric-tile">
          <div className="metric-label">Tokens Used</div>
          <div className="metric-value">
            {summary?.total_tokens_used != null
              ? summary.total_tokens_used.toLocaleString()
              : '—'}
          </div>
        </div>
      </div>

      {/* Latency chart */}
      {evals.length > 0 && (
        <div className="chart-container">
          <Line data={chartData} options={chartOptions} />
        </div>
      )}
    </div>
  );
}

export default MetricsChart;
