import { FastifyInstance } from 'fastify';
import { db, redis } from '../index.js';

const GAMMA_API = 'https://gamma-api.polymarket.com';
const CLOB_API = 'https://clob.polymarket.com';
const REQUEST_TIMEOUT = 10000;
const CACHE_TTL = 30; // seconds

// Helper to fetch with caching
async function cachedFetch(url: string, cacheKey: string): Promise<any> {
  // Try cache first
  const cached = await redis.get(cacheKey);
  if (cached) {
    return JSON.parse(cached);
  }
  
  // Fetch from API
  const response = await fetch(url, {
    signal: AbortSignal.timeout(REQUEST_TIMEOUT)
  });
  
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  
  const data = await response.json();
  
  // Cache the result
  await redis.setex(cacheKey, CACHE_TTL, JSON.stringify(data));
  
  return data;
}

export default async function polymarketRoutes(app: FastifyInstance) {
  // Get all Polymarket markets from DB
  app.get('/markets/polymarket', async (request) => {
    const client = await db.connect();
    try {
      const result = await client.query(`
        SELECT 
          m.id, m.symbol, m.name, m.type, m.source, m.metadata, m.is_active,
          (SELECT close FROM market_candles c 
           WHERE c.market_id = m.id AND c.interval = '1m' 
           ORDER BY timestamp DESC LIMIT 1) as latest_price,
          (SELECT timestamp FROM market_candles c 
           WHERE c.market_id = m.id AND c.interval = '1m' 
           ORDER BY timestamp DESC LIMIT 1) as last_candle_at
        FROM markets m
        WHERE m.source = 'POLYMARKET'
        ORDER BY m.created_at DESC
      `);
      
      return {
        total: result.rows.length,
        markets: result.rows.map(r => ({
          id: r.id,
          symbol: r.symbol,
          name: r.name,
          price: r.latest_price,
          last_update: r.last_candle_at,
          question: r.metadata?.question,
          outcomes: r.metadata?.outcomes,
          event_slug: r.metadata?.event_slug,
          end_date: r.metadata?.end_date,
          volume: r.metadata?.volume,
          is_active: r.is_active
        }))
      };
    } finally {
      client.release();
    }
  });

  // Get live orderbook for a market
  app.get<{ Params: { id: string } }>('/markets/:id/orderbook', async (request) => {
    const { id } = request.params;
    
    // Get market metadata to find token IDs
    const client = await db.connect();
    try {
      const result = await client.query(
        'SELECT metadata FROM markets WHERE id = $1',
        [id]
      );
      
      if (result.rows.length === 0) {
        return { error: 'Market not found' };
      }
      
      const metadata = result.rows[0].metadata || {};
      const tokenIds = metadata.token_ids || [];
      
      if (tokenIds.length === 0) {
        return { error: 'No token IDs found for this market' };
      }
      
      // Fetch orderbook for first token
      const tokenId = tokenIds[0];
      const cacheKey = `poly:book:${tokenId}`;
      
      try {
        const orderbook = await cachedFetch(
          `${CLOB_API}/book?token_id=${tokenId}`,
          cacheKey
        );
        
        const bids = orderbook.bids || [];
        const asks = orderbook.asks || [];
        
        // Calculate mid price and spread
        let midPrice = null;
        let spread = null;
        
        if (bids.length > 0 && asks.length > 0) {
          const bestBid = parseFloat(bids[0].price);
          const bestAsk = parseFloat(asks[0].price);
          midPrice = (bestBid + bestAsk) / 2;
          spread = bestAsk - bestBid;
        } else if (bids.length > 0) {
          midPrice = parseFloat(bids[0].price);
        } else if (asks.length > 0) {
          midPrice = parseFloat(asks[0].price);
        }
        
        return {
          market_id: id,
          token_id: tokenId,
          bids: bids.slice(0, 10),
          asks: asks.slice(0, 10),
          mid_price: midPrice,
          spread,
          best_bid: bids[0]?.price || null,
          best_ask: asks[0]?.price || null,
          cached: false
        };
      } catch (e: any) {
        return { error: 'Failed to fetch orderbook', message: e.message };
      }
    } finally {
      client.release();
    }
  });

  // Get latest price for a market
  app.get<{ Params: { id: string } }>('/markets/:id/price', async (request) => {
    const { id } = request.params;
    
    const client = await db.connect();
    try {
      const result = await client.query(`
        SELECT 
          m.symbol, m.metadata,
          c.close as price, c.timestamp
        FROM markets m
        LEFT JOIN LATERAL (
          SELECT close, timestamp 
          FROM market_candles 
          WHERE market_id = m.id AND interval = '1m'
          ORDER BY timestamp DESC LIMIT 1
        ) c ON true
        WHERE m.id = $1
      `, [id]);
      
      if (result.rows.length === 0) {
        return { error: 'Market not found' };
      }
      
      const row = result.rows[0];
      
      return {
        market_id: id,
        symbol: row.symbol,
        price: row.price,
        timestamp: row.timestamp,
        question: row.metadata?.question,
        outcome: row.metadata?.outcomes?.[0]
      };
    } finally {
      client.release();
    }
  });

  // Search Polymarket events
  app.get<{ Querystring: { q?: string; limit?: number } }>('/polymarket/search', async (request) => {
    const { q = '', limit = 20 } = request.query;
    
    const client = await db.connect();
    try {
      let query = `
        SELECT id, symbol, name, metadata, is_active
        FROM markets
        WHERE source = 'POLYMARKET'
      `;
      const params: any[] = [];
      
      if (q) {
        params.push(`%${q.toLowerCase()}%`);
        query += ` AND (LOWER(name) LIKE $1 OR LOWER(metadata->>'question') LIKE $1)`;
      }
      
      query += ` ORDER BY created_at DESC LIMIT ${parseInt(String(limit))}`;
      
      const result = await client.query(query, params);
      
      return {
        query: q,
        total: result.rows.length,
        results: result.rows.map(r => ({
          id: r.id,
          symbol: r.symbol,
          name: r.name,
          question: r.metadata?.question,
          outcomes: r.metadata?.outcomes,
          event_slug: r.metadata?.event_slug,
          is_active: r.is_active
        }))
      };
    } finally {
      client.release();
    }
  });

  // Trigger market discovery (manual sync)
  app.post('/polymarket/sync', async (request) => {
    // This would normally trigger the worker
    // For now, return a placeholder
    return {
      message: 'Market sync triggered',
      note: 'Check worker logs for progress'
    };
  });
}
