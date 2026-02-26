import { FastifyInstance } from 'fastify';
import { db } from '../index.js';

// Helper to check indicator sanity
function checkIndicatorSanity(indicators: any): { valid: boolean; alerts: string[] } {
  const alerts: string[] = [];
  
  if (!indicators) {
    return { valid: true, alerts: [] };
  }
  
  const adx = parseFloat(indicators.adx) || 0;
  const rsi = parseFloat(indicators.rsi) || 0;
  
  if (adx < 0 || adx > 100) {
    alerts.push(`ADX=${adx} is outside valid range [0, 100]`);
  }
  if (rsi < 0 || rsi > 100) {
    alerts.push(`RSI=${rsi} is outside valid range [0, 100]`);
  }
  
  return { valid: alerts.length === 0, alerts };
}

export default async function indicatorsRoutes(app: FastifyInstance) {
  // Get latest indicators for a market
  app.get<{
    Querystring: { market_id?: string; symbol?: string; interval?: string };
  }>('/indicators', async (request) => {
    const { market_id, symbol, interval = '1m' } = request.query;
    
    if (!market_id && !symbol) {
      return { error: 'market_id or symbol required' };
    }
    
    const client = await db.connect();
    try {
      let marketIdValue = market_id;
      
      // Resolve symbol to market_id
      if (!marketIdValue && symbol) {
        const res = await client.query(
          'SELECT id FROM markets WHERE symbol = $1 AND is_active = true',
          [symbol]
        );
        if (res.rows.length === 0) {
          return { error: 'Market not found' };
        }
        marketIdValue = res.rows[0].id;
      }
      
      // Get latest indicators
      const res = await client.query(
        `SELECT 
          i.*,
          m.symbol, m.name as market_name
        FROM market_indicators i
        JOIN markets m ON i.market_id = m.id
        WHERE i.market_id = $1 AND i.interval = $2
        ORDER BY i.timestamp DESC
        LIMIT 1`,
        [marketIdValue, interval]
      );
      
      if (res.rows.length === 0) {
        return {
          market_id: marketIdValue,
          interval,
          indicators: null,
          message: 'No indicators computed yet'
        };
      }
      
      const indicators = res.rows[0];
      const sanity = checkIndicatorSanity(indicators);
      
      return {
        market_id: marketIdValue,
        interval,
        indicators,
        sanity: sanity.valid ? 'ok' : 'warning',
        alerts: sanity.alerts.length > 0 ? sanity.alerts : undefined
      };
    } finally {
      client.release();
    }
  });

  // Get indicator sanity summary for all markets
  app.get('/indicators/sanity', async (request) => {
    const client = await db.connect();
    try {
      // Get latest indicators for all markets/intervals
      const res = await client.query(`
        WITH latest AS (
          SELECT DISTINCT ON (market_id, interval)
            market_id, interval, timestamp, adx, rsi, adx_trend
          FROM market_indicators
          ORDER BY market_id, interval, timestamp DESC
        )
        SELECT 
          l.*,
          m.symbol,
          m.name as market_name,
          CASE 
            WHEN l.adx::numeric < 0 OR l.adx::numeric > 100 THEN true
            WHEN l.rsi::numeric < 0 OR l.rsi::numeric > 100 THEN true
            ELSE false
          END as has_alert
        FROM latest l
        JOIN markets m ON l.market_id = m.id
        ORDER BY m.symbol, l.interval
      `);
      
      const alerts = res.rows.filter(r => r.has_alert);
      
      return {
        total_indicators: res.rows.length,
        alert_count: alerts.length,
        status: alerts.length === 0 ? 'all_ok' : 'has_warnings',
        alerts: alerts.map(a => ({
          symbol: a.symbol,
          interval: a.interval,
          timestamp: a.timestamp,
          adx: a.adx,
          rsi: a.rsi,
          issues: [
            ...(parseFloat(a.adx) < 0 || parseFloat(a.adx) > 100 ? [`ADX=${a.adx}`] : []),
            ...(parseFloat(a.rsi) < 0 || parseFloat(a.rsi) > 100 ? [`RSI=${a.rsi}`] : [])
          ].join(', ')
        })),
        all_indicators: res.rows.map(r => ({
          symbol: r.symbol,
          interval: r.interval,
          timestamp: r.timestamp,
          adx: r.adx,
          adx_trend: r.adx_trend,
          rsi: r.rsi,
          has_alert: r.has_alert
        }))
      };
    } finally {
      client.release();
    }
  });

  // Get indicator history
  app.get<{
    Querystring: { market_id?: string; symbol?: string; interval?: string; limit?: number };
  }>('/indicators/history', async (request) => {
    const { market_id, symbol, interval = '1m', limit = 50 } = request.query;
    
    if (!market_id && !symbol) {
      return { error: 'market_id or symbol required' };
    }
    
    const client = await db.connect();
    try {
      let marketIdValue = market_id;
      
      if (!marketIdValue && symbol) {
        const res = await client.query(
          'SELECT id FROM markets WHERE symbol = $1 AND is_active = true',
          [symbol]
        );
        if (res.rows.length === 0) {
          return { error: 'Market not found' };
        }
        marketIdValue = res.rows[0].id;
      }
      
      const res = await client.query(
        `SELECT * FROM market_indicators
        WHERE market_id = $1 AND interval = $2
        ORDER BY timestamp DESC
        LIMIT $3`,
        [marketIdValue, interval, limit]
      );
      
      return {
        market_id: marketIdValue,
        interval,
        history: res.rows.reverse() // Oldest first
      };
    } finally {
      client.release();
    }
  });

  // Get latest candle
  app.get<{
    Querystring: { market_id?: string; symbol?: string; interval?: string };
  }>('/candles/latest', async (request) => {
    const { market_id, symbol, interval = '1m' } = request.query;
    
    if (!market_id && !symbol) {
      return { error: 'market_id or symbol required' };
    }
    
    const client = await db.connect();
    try {
      let marketIdValue = market_id;
      
      if (!marketIdValue && symbol) {
        const res = await client.query(
          'SELECT id FROM markets WHERE symbol = $1 AND is_active = true',
          [symbol]
        );
        if (res.rows.length === 0) {
          return { error: 'Market not found' };
        }
        marketIdValue = res.rows[0].id;
      }
      
      const res = await client.query(
        `SELECT c.*, m.symbol, m.name as market_name
        FROM market_candles c
        JOIN markets m ON c.market_id = m.id
        WHERE c.market_id = $1 AND c.interval = $2
        ORDER BY c.timestamp DESC
        LIMIT 1`,
        [marketIdValue, interval]
      );
      
      return {
        market_id: marketIdValue,
        interval,
        candle: res.rows[0] || null
      };
    } finally {
      client.release();
    }
  });
}
