import { FastifyInstance } from 'fastify';
import { db } from '../index.js';

export default async function marketsRoutes(app: FastifyInstance) {
  // List all markets
  app.get('/', async () => {
    const result = await db.query(`
      SELECT id, symbol, type, source, name, tick_size, min_quantity, metadata, is_active, created_at
      FROM markets
      WHERE is_active = true
      ORDER BY type, symbol
    `);
    return { markets: result.rows };
  });

  // Get single market
  app.get<{ Params: { id: string } }>('/:id', async (request, reply) => {
    const { id } = request.params;
    const result = await db.query(`
      SELECT id, symbol, type, source, name, tick_size, min_quantity, metadata, is_active, created_at
      FROM markets WHERE id = $1
    `, [id]);
    
    if (result.rows.length === 0) {
      return reply.status(404).send({ error: 'Market not found' });
    }
    return result.rows[0];
  });

  // Get latest price
  app.get<{ Params: { id: string } }>('/:id/price', async (request, reply) => {
    const { id } = request.params;
    const result = await db.query(`
      SELECT close as price, timestamp
      FROM market_candles
      WHERE market_id = $1
      ORDER BY timestamp DESC
      LIMIT 1
    `, [id]);
    
    if (result.rows.length === 0) {
      return reply.status(404).send({ error: 'No price data available' });
    }
    return result.rows[0];
  });

  // Get OHLCV candles
  app.get<{ Params: { id: string }; Querystring: { interval?: string; limit?: number } }>('/:id/ohlcv', async (request) => {
    const { id } = request.params;
    const { interval = '1h', limit = 100 } = request.query;
    
    const result = await db.query(`
      SELECT timestamp, open, high, low, close, volume
      FROM market_candles
      WHERE market_id = $1 AND interval = $2
      ORDER BY timestamp DESC
      LIMIT $3
    `, [id, interval, limit]);
    
    return { candles: result.rows.reverse() };
  });
}
