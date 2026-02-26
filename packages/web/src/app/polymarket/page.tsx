'use client';

import { useState, useEffect } from 'react';

interface Market {
  id: string;
  symbol: string;
  name: string;
  price: number;
  question: string;
  outcomes: string[];
  event_slug: string;
  volume: number;
  is_active: boolean;
  last_update: string;
}

export default function PolymarketPage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    fetchMarkets();
  }, []);

  const fetchMarkets = async () => {
    try {
      setLoading(true);
      const response = await fetch('http://localhost:3001/api/v1/markets/polymarket');
      const data = await response.json();
      setMarkets(data.markets || []);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const filteredMarkets = markets.filter(m => 
    m.question?.toLowerCase().includes(search.toLowerCase()) ||
    m.symbol?.toLowerCase().includes(search.toLowerCase())
  );

  const formatPrice = (price: number) => {
    if (price === null || price === undefined) return '—';
    return `${(price * 100).toFixed(1)}¢`;
  };

  const formatVolume = (volume: number) => {
    if (!volume) return '—';
    if (volume >= 1e6) return `$${(volume / 1e6).toFixed(1)}M`;
    if (volume >= 1e3) return `$${(volume / 1e3).toFixed(1)}K`;
    return `$${volume}`;
  };

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Polymarket</h1>
            <p className="text-gray-600 mt-1">Prediction Markets</p>
          </div>
          <button
            onClick={fetchMarkets}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            Refresh
          </button>
        </div>

        {/* Search */}
        <div className="mb-6">
          <input
            type="text"
            placeholder="Search markets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        {/* Status */}
        {loading && <p className="text-gray-600">Loading markets...</p>}
        {error && <p className="text-red-600">Error: {error}</p>}

        {/* Markets Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredMarkets.map((market) => (
            <div
              key={market.id}
              className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 hover:shadow-md transition-shadow"
            >
              <div className="flex justify-between items-start mb-2">
                <span className="text-xs font-mono text-gray-500">
                  {market.symbol}
                </span>
                <span className="text-lg font-bold text-green-600">
                  {formatPrice(market.price)}
                </span>
              </div>
              
              <h3 className="text-sm font-medium text-gray-900 mb-2 line-clamp-2">
                {market.question || market.name}
              </h3>
              
              {market.outcomes && market.outcomes.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-3">
                  {market.outcomes.slice(0, 3).map((outcome, i) => (
                    <span
                      key={i}
                      className="text-xs px-2 py-1 bg-gray-100 text-gray-700 rounded"
                    >
                      {outcome}
                    </span>
                  ))}
                </div>
              )}
              
              <div className="flex justify-between items-center text-xs text-gray-500">
                <span>Vol: {formatVolume(market.volume)}</span>
                <span className={market.is_active ? 'text-green-600' : 'text-red-600'}>
                  {market.is_active ? 'Active' : 'Closed'}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Empty state */}
        {!loading && filteredMarkets.length === 0 && (
          <div className="text-center py-12 text-gray-500">
            <p>No markets found</p>
            <p className="text-sm mt-2">
              Markets are synced by the worker. Check worker logs.
            </p>
          </div>
        )}

        {/* Stats */}
        <div className="mt-8 p-4 bg-white rounded-lg border border-gray-200">
          <div className="flex justify-around text-center">
            <div>
              <p className="text-2xl font-bold text-gray-900">{markets.length}</p>
              <p className="text-sm text-gray-600">Total Markets</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-green-600">
                {markets.filter(m => m.is_active).length}
              </p>
              <p className="text-sm text-gray-600">Active</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-blue-600">
                {markets.filter(m => m.price).length}
              </p>
              <p className="text-sm text-gray-600">With Prices</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
