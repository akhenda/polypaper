import { fetchDashboard } from '@/lib/api';

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString();
}

export default async function DashboardPage() {
  let data;
  try {
    data = await fetchDashboard();
  } catch (e) {
    return (
      <div className="container">
        <div className="error-panel">
          <h3>Failed to load dashboard</h3>
          <p>Make sure the API is running at {process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3001'}</p>
          <p style={{ marginTop: 10, fontSize: 12, color: '#94a3b8' }}>
            Run: docker compose up -d --build
          </p>
        </div>
      </div>
    );
  }

  const { account, stats, positions, strategies, recentTrades, errorLog } = data;

  return (
    <div className="container">
      <header className="header">
        <div>
          <h1 className="title">📊 Polypaper Dashboard</h1>
          <p className="subtitle">Paper Trading System • Account: {account?.name || 'N/A'}</p>
        </div>
      </header>

      {/* Main Stats */}
      <div className="grid grid-4" style={{ marginBottom: 20 }}>
        <div className="stat-card">
          <div className="stat-label">Equity</div>
          <div className="stat-value">{formatCurrency(account?.equity || 0)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total P/L</div>
          <div className={`stat-value ${account?.totalPnl >= 0 ? 'positive' : 'negative'}`}>
            {formatCurrency(account?.totalPnl || 0)}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Win Rate</div>
          <div className="stat-value">{stats?.winRate?.toFixed(1) || 0}%</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Trades</div>
          <div className="stat-value">{stats?.totalTrades || 0}</div>
        </div>
      </div>

      {/* Strategies */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">🎯 Active Strategies</h2>
        </div>
        {strategies && strategies.length > 0 ? (
          <div className="grid grid-2">
            {strategies.map((s: any) => (
              <div key={s.id} className="strategy-card">
                <div className="strategy-header">
                  <span className="strategy-name">{s.id}</span>
                  <span className={`badge ${s.cooldownUntil ? 'badge-yellow' : 'badge-green'}`}>
                    {s.cooldownUntil ? 'COOLDOWN' : 'ACTIVE'}
                  </span>
                </div>
                <div className="strategy-stats">
                  <div className="strategy-stat">
                    <span className="strategy-stat-label">Capital: </span>
                    <span className="strategy-stat-value">{formatCurrency(s.totalPnl || 0)}</span>
                  </div>
                  <div className="strategy-stat">
                    <span className="strategy-stat-label">Win Rate: </span>
                    <span className="strategy-stat-value">{s.winRate?.toFixed(1) || 0}%</span>
                  </div>
                  <div className="strategy-stat">
                    <span className="strategy-stat-label">Trades: </span>
                    <span className="strategy-stat-value">{s.totalTrades || 0}</span>
                  </div>
                  <div className="strategy-stat">
                    <span className="strategy-stat-label">Loss Streak: </span>
                    <span className={`strategy-stat-value ${s.consecutiveLosses >= 2 ? 'negative' : ''}`}>
                      {s.consecutiveLosses || 0}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: '#94a3b8' }}>No active strategies. The worker will activate strategies automatically.</p>
        )}
      </div>

      {/* Open Positions */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">📈 Open Positions</h2>
          <span className="badge badge-blue">{positions?.length || 0} positions</span>
        </div>
        {positions && positions.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Quantity</th>
                <th>Entry Price</th>
                <th>Current Price</th>
                <th>Unrealized P/L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p: any) => (
                <tr key={p.id}>
                  <td><strong>{p.symbol}</strong></td>
                  <td><span className="badge badge-green">{p.side}</span></td>
                  <td>{p.quantity}</td>
                  <td>{formatCurrency(p.avg_entry_price)}</td>
                  <td>{formatCurrency(p.currentPrice)}</td>
                  <td className={p.unrealizedPnl >= 0 ? 'positive' : 'negative'}>
                    {formatCurrency(p.unrealizedPnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: '#94a3b8' }}>No open positions</p>
        )}
      </div>

      {/* Recent Trades */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">🔄 Recent Trades</h2>
        </div>
        {recentTrades && recentTrades.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Type</th>
                <th>Quantity</th>
                <th>Price</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {recentTrades.slice(0, 10).map((t: any) => (
                <tr key={t.id}>
                  <td style={{ fontSize: 12 }}>{formatTime(t.created_at)}</td>
                  <td><strong>{t.symbol}</strong></td>
                  <td>
                    <span className={`badge ${t.side === 'BUY' ? 'badge-green' : 'badge-red'}`}>
                      {t.side}
                    </span>
                  </td>
                  <td>{t.type}</td>
                  <td>{t.quantity}</td>
                  <td>{formatCurrency(t.avg_fill_price)}</td>
                  <td>
                    <span className={`badge ${t.status === 'FILLED' ? 'badge-green' : 'badge-yellow'}`}>
                      {t.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: '#94a3b8' }}>No trades yet</p>
        )}
      </div>

      {/* Error Log */}
      {errorLog && errorLog.length > 0 && (
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">⚠️ Error Log (Last 50)</h2>
          </div>
          <div className="error-panel">
            {errorLog.map((e: any) => (
              <div key={e.id} className="error-item">
                <div className="error-time">{formatTime(e.created_at)} • {e.source}</div>
                <div className="error-message">{e.message}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
