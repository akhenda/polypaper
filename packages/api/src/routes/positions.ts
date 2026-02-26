import { FastifyInstance } from 'fastify';
import { db } from '../index.js';

export default async function positionsRoutes(app: FastifyInstance) {
  // List open positions
  app.get<{ Querystring: { accountId?: string; open?: boolean } }>('/', async (request) => {
    const { accountId, open } = request.query;
    let query = `
      SELECT p.*, m.symbol as market_symbol, m.name as market_name, m.type as market_type
      FROM positions p
      JOIN markets m ON p.market_id = m.id
      WHERE 1=1
    `;
    const params: any[] = [];
    
    if (accountId) {
      params.push(accountId);
      query += ` AND p.account_id = $${params.length}`;
    }
    if (open !== undefined) {
      params.push(open === true || open === 'true');
      query += ` AND p.is_open = $${params.length}`;
    }
    
    query += ' ORDER BY p.opened_at DESC';
    
    const result = await db.query(query, params);
    
    // Add current price and unrealized PnL for open positions
    const positions = await Promise.all(result.rows.map(async (pos) => {
      if (!pos.is_open) return pos;
      
      const priceResult = await db.query(`
        SELECT close as price FROM market_candles
        WHERE market_id = $1 ORDER BY timestamp DESC LIMIT 1
      `, [pos.market_id]);
      
      const currentPrice = priceResult.rows[0]?.price || pos.avg_entry_price;
      const unrealizedPnl = pos.side === 'LONG' || pos.side === 'YES'
        ? (parseFloat(currentPrice) - parseFloat(pos.avg_entry_price)) * parseFloat(pos.quantity)
        : (parseFloat(pos.avg_entry_price) - parseFloat(currentPrice)) * parseFloat(pos.quantity);
      
      return {
        ...pos,
        currentPrice,
        unrealizedPnl,
        unrealizedPnlPercent: parseFloat(pos.avg_entry_price) > 0 
          ? (unrealizedPnl / (parseFloat(pos.avg_entry_price) * parseFloat(pos.quantity))) * 100 
          : 0
      };
    }));
    
    return { positions };
  });

  // Get single position
  app.get<{ Params: { id: string } }>('/:id', async (request, reply) => {
    const { id } = request.params;
    const result = await db.query(`
      SELECT p.*, m.symbol as market_symbol, m.name as market_name
      FROM positions p
      JOIN markets m ON p.market_id = m.id
      WHERE p.id = $1
    `, [id]);
    
    if (result.rows.length === 0) {
      return reply.status(404).send({ error: 'Position not found' });
    }
    return result.rows[0];
  });

  // Get position history (closed positions)
  app.get<{ Querystring: { accountId?: string; limit?: number } }>('/history', async (request) => {
    const { accountId, limit = 50 } = request.query;
    let query = `
      SELECT p.*, m.symbol as market_symbol, m.name as market_name
      FROM positions p
      JOIN markets m ON p.market_id = m.id
      WHERE p.is_open = false
    `;
    const params: any[] = [];
    
    if (accountId) {
      params.push(accountId);
      query += ` AND p.account_id = $${params.length}`;
    }
    
    query += ` ORDER BY p.closed_at DESC LIMIT $${params.length + 1}`;
    params.push(limit);
    
    const result = await db.query(query, params);
    return { positions: result.rows };
  });
}
