import { FastifyInstance } from 'fastify';
import { db } from '../index.js';
import { v4 as uuidv4 } from 'uuid';

interface CreateOrderBody {
  accountId: string;
  marketId: string;
  side: 'BUY' | 'SELL';
  type: 'MARKET' | 'LIMIT';
  quantity: number;
  price?: number;
  strategyId?: string;
}

export default async function ordersRoutes(app: FastifyInstance) {
  // List orders
  app.get<{ Querystring: { accountId?: string; status?: string; limit?: number } }>('/', async (request) => {
    const { accountId, status, limit = 50 } = request.query;
    let query = `
      SELECT o.*, m.symbol as market_symbol, m.name as market_name
      FROM orders o
      JOIN markets m ON o.market_id = m.id
      WHERE 1=1
    `;
    const params: any[] = [];
    
    if (accountId) {
      params.push(accountId);
      query += ` AND o.account_id = $${params.length}`;
    }
    if (status) {
      params.push(status);
      query += ` AND o.status = $${params.length}`;
    }
    
    query += ` ORDER BY o.created_at DESC LIMIT $${params.length + 1}`;
    params.push(limit);
    
    const result = await db.query(query, params);
    return { orders: result.rows };
  });

  // Get single order
  app.get<{ Params: { id: string } }>('/:id', async (request, reply) => {
    const { id } = request.params;
    const result = await db.query(`
      SELECT o.*, m.symbol as market_symbol, m.name as market_name
      FROM orders o
      JOIN markets m ON o.market_id = m.id
      WHERE o.id = $1
    `, [id]);
    
    if (result.rows.length === 0) {
      return reply.status(404).send({ error: 'Order not found' });
    }
    return result.rows[0];
  });

  // Create order (paper trading - fills immediately for market orders)
  app.post<{ Body: CreateOrderBody }>('/', async (request, reply) => {
    const { accountId, marketId, side, type, quantity, price, strategyId } = request.body;
    
    // Get current market price
    const priceResult = await db.query(`
      SELECT close as price FROM market_candles
      WHERE market_id = $1 ORDER BY timestamp DESC LIMIT 1
    `, [marketId]);
    
    if (priceResult.rows.length === 0) {
      return reply.status(400).send({ error: 'No price data available for market' });
    }
    
    const currentPrice = parseFloat(priceResult.rows[0].price);
    const fillPrice = type === 'MARKET' ? currentPrice : (price || currentPrice);
    
    // Check account balance for BUY orders
    if (side === 'BUY') {
      const balanceResult = await db.query(`
        SELECT current_balance FROM accounts WHERE id = $1
      `, [accountId]);
      
      if (balanceResult.rows.length === 0) {
        return reply.status(404).send({ error: 'Account not found' });
      }
      
      const balance = parseFloat(balanceResult.rows[0].current_balance);
      const orderCost = quantity * fillPrice;
      
      if (orderCost > balance) {
        return reply.status(400).send({ error: 'Insufficient balance' });
      }
    }

    const client = await db.connect();
    try {
      await client.query('BEGIN');
      
      // Create order
      const orderResult = await client.query(`
        INSERT INTO orders (id, account_id, market_id, strategy_id, side, type, quantity, price, filled_quantity, avg_fill_price, status, filled_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'FILLED', NOW())
        RETURNING *
      `, [uuidv4(), accountId, marketId, strategyId || null, side, type, quantity, price || null, quantity, fillPrice]);
      
      const order = orderResult.rows[0];
      
      // Update account balance
      const balanceChange = side === 'BUY' ? -(quantity * fillPrice) : (quantity * fillPrice);
      await client.query(`
        UPDATE accounts SET current_balance = current_balance + $1 WHERE id = $2
      `, [balanceChange, accountId]);
      
      // Handle position
      if (side === 'BUY') {
        // Check for existing open position
        const posResult = await client.query(`
          SELECT id, quantity, avg_entry_price FROM positions
          WHERE account_id = $1 AND market_id = $2 AND is_open = true
        `, [accountId, marketId]);
        
        if (posResult.rows.length > 0) {
          // Update existing position
          const existing = posResult.rows[0];
          const newQty = parseFloat(existing.quantity) + quantity;
          const newAvg = ((parseFloat(existing.avg_entry_price) * parseFloat(existing.quantity)) + (fillPrice * quantity)) / newQty;
          await client.query(`
            UPDATE positions SET quantity = $1, avg_entry_price = $2 WHERE id = $3
          `, [newQty, newAvg, existing.id]);
        } else {
          // Create new position
          await client.query(`
            INSERT INTO positions (id, account_id, market_id, strategy_id, side, quantity, avg_entry_price, is_open)
            VALUES ($1, $2, $3, $4, 'LONG', $5, $6, true)
          `, [uuidv4(), accountId, marketId, strategyId || null, quantity, fillPrice]);
        }
      } else {
        // SELL - close or reduce position
        const posResult = await client.query(`
          SELECT id, quantity, avg_entry_price FROM positions
          WHERE account_id = $1 AND market_id = $2 AND is_open = true
        `, [accountId, marketId]);
        
        if (posResult.rows.length === 0) {
          throw new Error('No open position to sell');
        }
        
        const existing = posResult.rows[0];
        const existingQty = parseFloat(existing.quantity);
        const pnl = (fillPrice - parseFloat(existing.avg_entry_price)) * quantity;
        
        if (quantity >= existingQty) {
          // Close position
          await client.query(`
            UPDATE positions SET is_open = false, closed_at = NOW(), realized_pnl = $1 WHERE id = $2
          `, [pnl, existing.id]);
        } else {
          // Reduce position
          await client.query(`
            UPDATE positions SET quantity = quantity - $1, realized_pnl = realized_pnl + $2 WHERE id = $3
          `, [quantity, pnl, existing.id]);
        }
        
        // Log realized PnL
        await client.query(`
          INSERT INTO trade_log (account_id, order_id, position_id, action, details)
          VALUES ($1, $2, $3, 'POSITION_CLOSE', $4)
        `, [accountId, order.id, existing.id, JSON.stringify({ pnl, quantity, price: fillPrice })]);
      }
      
      await client.query('COMMIT');
      return reply.status(201).send(order);
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  });

  // Cancel order (only pending orders)
  app.delete<{ Params: { id: string } }>('/:id', async (request, reply) => {
    const { id } = request.params;
    
    const result = await db.query(`
      UPDATE orders SET status = 'CANCELLED' WHERE id = $1 AND status = 'PENDING'
      RETURNING *
    `, [id]);
    
    if (result.rows.length === 0) {
      return reply.status(404).send({ error: 'Order not found or cannot be cancelled' });
    }
    return result.rows[0];
  });
}
