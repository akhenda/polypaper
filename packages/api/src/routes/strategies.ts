import { FastifyInstance } from 'fastify';
import { db } from '../index.js';
import { v4 as uuidv4 } from 'uuid';

// Available strategies (static for now, will be dynamic later)
const AVAILABLE_STRATEGIES = [
  {
    id: 'late-entry-v1',
    name: 'Late Entry',
    description: 'Enters trades during favorable volatility conditions with position cap and circuit breaker',
    version: '1.0.0',
    markets: ['CRYPTO'],
    parameters: [
      { name: 'positionCapUsd', type: 'number', default: 20, description: 'Maximum position size in USD' },
      { name: 'volatilityThreshold', type: 'number', default: 0.02, description: 'Minimum volatility to trigger entry' },
      { name: 'maxConsecutiveLosses', type: 'number', default: 3, description: 'Circuit breaker threshold' },
      { name: 'cooldownHours', type: 'number', default: 24, description: 'Cooldown period after circuit breaker' }
    ]
  }
];

export default async function strategiesRoutes(app: FastifyInstance) {
  // List available strategies
  app.get('/', async () => {
    return { strategies: AVAILABLE_STRATEGIES };
  });

  // Get strategy details
  app.get<{ Params: { id: string } }>('/:id', async (request, reply) => {
    const { id } = request.params;
    const strategy = AVAILABLE_STRATEGIES.find(s => s.id === id);
    if (!strategy) {
      return reply.status(404).send({ error: 'Strategy not found' });
    }
    return strategy;
  });

  // List active strategy instances
  app.get<{ Querystring: { accountId?: string } }>('/instances', async (request) => {
    const { accountId } = request.query;
    let query = `
      SELECT si.*, a.name as account_name
      FROM strategy_instances si
      JOIN accounts a ON si.account_id = a.id
      WHERE 1=1
    `;
    const params: any[] = [];
    
    if (accountId) {
      params.push(accountId);
      query += ` AND si.account_id = $${params.length}`;
    }
    
    query += ' ORDER BY si.created_at DESC';
    
    const result = await db.query(query, params);
    return { instances: result.rows };
  });

  // Activate strategy for account
  app.post<{ Params: { id: string }; Body: { accountId: string; parameters?: Record<string, any> } }>('/:id/activate', async (request, reply) => {
    const { id } = request.params;
    const { accountId, parameters = {} } = request.body;
    
    const strategy = AVAILABLE_STRATEGIES.find(s => s.id === id);
    if (!strategy) {
      return reply.status(404).send({ error: 'Strategy not found' });
    }
    
    // Check if already active
    const existing = await db.query(`
      SELECT id FROM strategy_instances WHERE account_id = $1 AND strategy_id = $2 AND is_active = true
    `, [accountId, id]);
    
    if (existing.rows.length > 0) {
      return reply.status(400).send({ error: 'Strategy already active for this account' });
    }
    
    // Create strategy instance
    const result = await db.query(`
      INSERT INTO strategy_instances (id, account_id, strategy_id, parameters, is_active)
      VALUES ($1, $2, $3, $4, true)
      RETURNING *
    `, [uuidv4(), accountId, id, JSON.stringify(parameters)]);
    
    // Initialize strategy state
    await db.query(`
      INSERT INTO strategy_state (account_id, strategy_id)
      VALUES ($1, $2)
      ON CONFLICT (account_id, strategy_id) DO NOTHING
    `, [accountId, id]);
    
    return reply.status(201).send(result.rows[0]);
  });

  // Deactivate strategy
  app.post<{ Params: { id: string }; Body: { accountId: string } }>('/:id/deactivate', async (request, reply) => {
    const { id } = request.params;
    const { accountId } = request.body;
    
    const result = await db.query(`
      UPDATE strategy_instances SET is_active = false WHERE account_id = $1 AND strategy_id = $2
      RETURNING *
    `, [accountId, id]);
    
    if (result.rows.length === 0) {
      return reply.status(404).send({ error: 'Active strategy instance not found' });
    }
    return result.rows[0];
  });

  // Get strategy performance
  app.get<{ Params: { id: string }; Querystring: { accountId: string } }>('/:id/performance', async (request, reply) => {
    const { id } = request.params;
    const { accountId } = request.query;
    
    if (!accountId) {
      return reply.status(400).send({ error: 'accountId required' });
    }
    
    // Get strategy state
    const stateResult = await db.query(`
      SELECT * FROM strategy_state WHERE account_id = $1 AND strategy_id = $2
    `, [accountId, id]);
    
    // Get trades from this strategy
    const tradesResult = await db.query(`
      SELECT o.*, m.symbol
      FROM orders o
      JOIN markets m ON o.market_id = m.id
      WHERE o.account_id = $1 AND o.strategy_id = $2 AND o.status = 'FILLED'
      ORDER BY o.created_at DESC
      LIMIT 100
    `, [accountId, id]);
    
    const state = stateResult.rows[0] || {
      consecutive_losses: 0,
      total_trades: 0,
      winning_trades: 0,
      total_pnl: 0
    };
    
    const winRate = state.total_trades > 0 ? (state.winning_trades / state.total_trades) * 100 : 0;
    
    return {
      strategyId: id,
      accountId,
      consecutiveLosses: state.consecutive_losses || 0,
      cooldownUntil: state.cooldown_until,
      totalTrades: state.total_trades || 0,
      winningTrades: state.winning_trades || 0,
      winRate,
      totalPnl: state.total_pnl || 0,
      recentTrades: tradesResult.rows
    };
  });
}
