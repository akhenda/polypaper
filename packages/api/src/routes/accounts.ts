import { FastifyInstance } from 'fastify';
import { db } from '../index.js';

export default async function accountsRoutes(app: FastifyInstance) {
  // List all accounts
  app.get('/', async () => {
    const result = await db.query(`
      SELECT id, name, currency, initial_balance, current_balance, is_active, created_at
      FROM accounts
      ORDER BY created_at DESC
    `);
    return { accounts: result.rows };
  });

  // Get single account
  app.get<{ Params: { id: string } }>('/:id', async (request, reply) => {
    const { id } = request.params;
    const result = await db.query(`
      SELECT id, name, currency, initial_balance, current_balance, is_active, created_at
      FROM accounts WHERE id = $1
    `, [id]);
    
    if (result.rows.length === 0) {
      return reply.status(404).send({ error: 'Account not found' });
    }

    // Calculate equity (balance + unrealized PnL)
    const positionsResult = await db.query(`
      SELECT COALESCE(SUM(
        CASE WHEN p.side IN ('LONG', 'YES') THEN 
          (p.quantity * (SELECT close FROM market_candles WHERE market_id = p.market_id ORDER BY timestamp DESC LIMIT 1) - p.avg_entry_price * p.quantity)
        ELSE
          (p.avg_entry_price * p.quantity - p.quantity * (SELECT close FROM market_candles WHERE market_id = p.market_id ORDER BY timestamp DESC LIMIT 1))
        END
      ), 0) as unrealized_pnl
      FROM positions p
      WHERE p.account_id = $1 AND p.is_open = true
    `, [id]);

    const account = result.rows[0];
    const unrealizedPnl = parseFloat(positionsResult.rows[0]?.unrealized_pnl || '0');
    
    return {
      ...account,
      equity: parseFloat(account.current_balance) + unrealizedPnl,
      unrealizedPnl,
    };
  });

  // Create account
  app.post<{ Body: { name: string; initialBalance: number; currency?: string } }>('/', async (request, reply) => {
    const { name, initialBalance, currency = 'USD' } = request.body;
    const result = await db.query(`
      INSERT INTO accounts (name, currency, initial_balance, current_balance)
      VALUES ($1, $2, $3, $3)
      RETURNING id, name, currency, initial_balance, current_balance, is_active, created_at
    `, [name, currency, initialBalance]);
    return reply.status(201).send(result.rows[0]);
  });

  // Reset account balance
  app.patch<{ Params: { id: string }; Body: { balance?: number } }>('/:id', async (request, reply) => {
    const { id } = request.params;
    const { balance } = request.body;
    
    if (balance !== undefined) {
      await db.query(`UPDATE accounts SET current_balance = $1 WHERE id = $2`, [balance, id]);
    }
    
    const result = await db.query(`
      SELECT id, name, currency, initial_balance, current_balance, is_active, created_at
      FROM accounts WHERE id = $1
    `, [id]);
    return result.rows[0];
  });
}
