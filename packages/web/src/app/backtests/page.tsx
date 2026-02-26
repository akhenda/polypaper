'use client';

import { useState, useEffect } from 'react';

interface Backtest {
  id: string;
  strategy_id: string;
  status: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_capital: number;
  total_return: number;
  win_rate: number;
  max_drawdown: number;
  sharpe_ratio: number;
  trade_count: number;
  symbols: string[];
  created_at: string;
}

interface BacktestDetail extends Backtest {
  equity_curve: Array<{ time: string; equity: number }>;
  trades: Array<{
    entry_time: string;
    exit_time: string;
    symbol: string;
    entry_price: number;
    exit_price: number;
    quantity: number;
    pnl: number;
    pnl_percent: number;
  }>;
  metadata: {
    monte_carlo?: {
      equity_p5: number;
      equity_p50: number;
      equity_p95: number;
      prob_ruin: number;
      prob_profit: number;
    };
  };
}

export default function BacktestsPage() {
  const [backtests, setBacktests] = useState<Backtest[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacktestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchBacktests();
  }, []);

  useEffect(() => {
    if (selectedId) {
      fetchDetail(selectedId);
    }
  }, [selectedId]);

  const fetchBacktests = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://localhost:3001/api/v1/backtests');
      const data = await res.json();
      setBacktests(data.backtests || []);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchDetail = async (id: string) => {
    try {
      const res = await fetch(`http://localhost:3001/api/v1/backtests/${id}`);
      const data = await res.json();
      setDetail(data);
    } catch (e) {
      console.error('Failed to fetch detail:', e);
    }
  };

  const formatPercent = (val: number) => `${val >= 0 ? '+' : ''}${val.toFixed(2)}%`;
  const formatCurrency = (val: number) => `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLETED': return 'text-green-600';
      case 'PENDING': return 'text-yellow-600';
      case 'FAILED': return 'text-red-600';
      default: return 'text-gray-600';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 p-8">
        <p className="text-gray-600">Loading backtests...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">Backtests</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg mb-6">
            Error: {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Backtest List */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200">
            <div className="p-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold">All Backtests ({backtests.length})</h2>
            </div>
            <div className="divide-y divide-gray-100 max-h-[600px] overflow-y-auto">
              {backtests.length === 0 ? (
                <div className="p-8 text-center text-gray-500">
                  <p>No backtests yet</p>
                  <p className="text-sm mt-2">Run a backtest via API or worker</p>
                </div>
              ) : (
                backtests.map((bt) => (
                  <button
                    key={bt.id}
                    onClick={() => setSelectedId(bt.id)}
                    className={`w-full p-4 text-left hover:bg-gray-50 transition-colors ${
                      selectedId === bt.id ? 'bg-blue-50' : ''
                    }`}
                  >
                    <div className="flex justify-between items-start mb-1">
                      <span className="font-medium text-gray-900">{bt.strategy_id}</span>
                      <span className={`text-sm font-medium ${getStatusColor(bt.status)}`}>
                        {bt.status}
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-sm">
                      <span className="text-gray-500">
                        {bt.symbols?.join(', ') || 'No markets'}
                      </span>
                      <span className={bt.total_return >= 0 ? 'text-green-600' : 'text-red-600'}>
                        {formatPercent(bt.total_return)}
                      </span>
                    </div>
                    <div className="text-xs text-gray-400 mt-1">
                      {bt.trade_count} trades • Win: {bt.win_rate.toFixed(1)}% • DD: {bt.max_drawdown.toFixed(1)}%
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>

          {/* Detail View */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200">
            {detail ? (
              <div>
                <div className="p-4 border-b border-gray-200">
                  <h2 className="text-lg font-semibold">{detail.strategy_id}</h2>
                  <p className="text-sm text-gray-500">
                    {detail.start_date?.slice(0, 10)} to {detail.end_date?.slice(0, 10)}
                  </p>
                </div>

                {/* Metrics Grid */}
                <div className="grid grid-cols-3 gap-4 p-4 border-b border-gray-200">
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Total Return</p>
                    <p className={`text-xl font-bold ${detail.total_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {formatPercent(detail.total_return)}
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Win Rate</p>
                    <p className="text-xl font-bold text-gray-900">{detail.win_rate.toFixed(1)}%</p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Max Drawdown</p>
                    <p className="text-xl font-bold text-red-600">{detail.max_drawdown.toFixed(1)}%</p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Sharpe</p>
                    <p className="text-xl font-bold text-gray-900">{detail.sharpe_ratio.toFixed(2)}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Trades</p>
                    <p className="text-xl font-bold text-gray-900">{detail.trade_count}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Final Capital</p>
                    <p className="text-xl font-bold text-gray-900">{formatCurrency(detail.final_capital)}</p>
                  </div>
                </div>

                {/* Monte Carlo Robustness */}
                {detail.metadata?.monte_carlo && (
                  <div className="p-4 border-b border-gray-200 bg-blue-50">
                    <h3 className="font-medium text-sm mb-2">Monte Carlo Robustness (1000 sims)</h3>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <span className="text-gray-500">Equity P5:</span>{' '}
                        <span className="font-medium">{formatCurrency(detail.metadata.monte_carlo.equity_p5)}</span>
                      </div>
                      <div>
                        <span className="text-gray-500">Equity P50:</span>{' '}
                        <span className="font-medium">{formatCurrency(detail.metadata.monte_carlo.equity_p50)}</span>
                      </div>
                      <div>
                        <span className="text-gray-500">Equity P95:</span>{' '}
                        <span className="font-medium">{formatCurrency(detail.metadata.monte_carlo.equity_p95)}</span>
                      </div>
                      <div>
                        <span className="text-gray-500">Prob Ruin:</span>{' '}
                        <span className="font-medium text-red-600">
                          {(detail.metadata.monte_carlo.prob_ruin * 100).toFixed(1)}%
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Equity Curve Placeholder */}
                <div className="p-4 border-b border-gray-200">
                  <h3 className="font-medium text-sm mb-2">Equity Curve</h3>
                  <div className="h-32 bg-gray-100 rounded flex items-center justify-center text-gray-400">
                    {detail.equity_curve?.length ? `${detail.equity_curve.length} data points` : 'No data'}
                  </div>
                </div>

                {/* Trades Table */}
                <div className="p-4">
                  <h3 className="font-medium text-sm mb-2">Trades ({detail.trades?.length || 0})</h3>
                  {detail.trades?.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="text-xs w-full">
                        <thead>
                          <tr className="text-gray-500 border-b">
                            <th className="text-left py-1">Entry</th>
                            <th className="text-right py-1">Price</th>
                            <th className="text-right py-1">Exit</th>
                            <th className="text-right py-1">PnL</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.trades.slice(0, 10).map((t, i) => (
                            <tr key={i} className="border-b border-gray-50">
                              <td className="py-1">{t.entry_time?.slice(0, 10)}</td>
                              <td className="text-right">{t.entry_price.toFixed(2)}</td>
                              <td className="text-right">{t.exit_price.toFixed(2)}</td>
                              <td className={`text-right font-medium ${t.pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                {formatPercent(t.pnl_percent)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-gray-400 text-sm">No trades</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-8 text-center text-gray-500">
                <p>Select a backtest to view details</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
