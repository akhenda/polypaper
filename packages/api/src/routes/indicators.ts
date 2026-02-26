import { FastifyInstance } from 'fastify';
import { Pool } from 'pg';

export default async function indicatorsRoutes(app: FastifyInstance, db: Pool) {
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
      
      return {
        market_id: marketIdValue,
        interval,
        indicators: res.rows[0]
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
