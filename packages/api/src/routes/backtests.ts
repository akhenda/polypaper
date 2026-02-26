import { FastifyInstance } from 'fastify';
import { db } from '../index.js';

export default async function backtestsRoutes(app: FastifyInstance) {
  // List all backtests
  app.get('/backtests', async (request) => {
    const client = await db.connect();
    try {
      const result = await client.query(`
        SELECT 
          b.id, b.strategy_id, b.status, b.start_date, b.end_date,
          b.initial_capital, b.final_capital, b.total_return,
          b.win_rate, b.max_drawdown, b.sharpe_ratio, b.trade_count,
          b.created_at, b.parameters,
          array_agg(DISTINCT m.symbol) as symbols
        FROM backtests b
        LEFT JOIN markets m ON m.id = ANY(b.market_ids)
        GROUP BY b.id
        ORDER BY b.created_at DESC
        LIMIT 100
      `);
      
      return {
        total: result.rows.length,
        backtests: result.rows.map(r => ({
          id: r.id,
          strategy_id: r.strategy_id,
          status: r.status,
          start_date: r.start_date,
          end_date: r.end_date,
          initial_capital: parseFloat(r.initial_capital),
          final_capital: parseFloat(r.final_capital),
          total_return: parseFloat(r.total_return),
          win_rate: parseFloat(r.win_rate),
          max_drawdown: parseFloat(r.max_drawdown),
          sharpe_ratio: parseFloat(r.sharpe_ratio),
          trade_count: r.trade_count,
          symbols: r.symbols.filter(Boolean),
          created_at: r.created_at
        }))
      };
    } finally {
      client.release();
    }
  });

  // Get single backtest with details
  app.get<{ Params: { id: string } }>('/backtests/:id', async (request) => {
    const { id } = request.params;
    
    const client = await db.connect();
    try {
      const result = await client.query(`
        SELECT b.*, array_agg(DISTINCT m.symbol) as symbols
        FROM backtests b
        LEFT JOIN markets m ON m.id = ANY(b.market_ids)
        WHERE b.id = $1
        GROUP BY b.id
      `, [id]);
      
      if (result.rows.length === 0) {
        return { error: 'Backtest not found' };
      }
      
      const row = result.rows[0];
      
      return {
        id: row.id,
        strategy_id: row.strategy_id,
        status: row.status,
        parameters: row.parameters,
        market_ids: row.market_ids,
        symbols: row.symbols.filter(Boolean),
        start_date: row.start_date,
        end_date: row.end_date,
        initial_capital: parseFloat(row.initial_capital),
        final_capital: parseFloat(row.final_capital),
        total_return: parseFloat(row.total_return),
        win_rate: parseFloat(row.win_rate),
        max_drawdown: parseFloat(row.max_drawdown),
        sharpe_ratio: parseFloat(row.sharpe_ratio),
        trade_count: row.trade_count,
        equity_curve: row.equity_curve,
        trades: row.trades,
        metadata: row.metadata,
        created_at: row.created_at
      };
    } finally {
      client.release();
    }
  });

  // Create new backtest (triggers worker job)
  app.post('/backtests', async (request) => {
    const body = request.body as any;
    
    const {
      strategy_id,
      parameters = {},
      market_ids,
      start_date,
      end_date,
      initial_capital = 10000,
      fee_bps = 2,
      slippage_bps = 5,
      position_cap_usd = 20,
      run_monte_carlo = false,
      monte_carlo_simulations = 1000
    } = body;
    
    if (!strategy_id || !market_ids || !start_date || !end_date) {
      return { error: 'Missing required fields: strategy_id, market_ids, start_date, end_date' };
    }
    
    const client = await db.connect();
    try {
      // Create backtest record with PENDING status
      const result = await client.query(`
        INSERT INTO backtests 
          (strategy_id, parameters, market_ids, start_date, end_date,
           initial_capital, final_capital, total_return, status, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $6, 0, 'PENDING', $7)
        RETURNING id
      `, [
        strategy_id,
        JSON.stringify({
          ...parameters,
          fee_bps,
          slippage_bps,
          position_cap_usd
        }),
        market_ids,
        start_date,
        end_date,
        initial_capital,
        JSON.stringify({
          run_monte_carlo,
          monte_carlo_simulations
        })
      ]);
      
      const backtestId = result.rows[0].id;
      
      // In production, this would trigger a worker job
      // For now, return the ID and let user poll
      return {
        id: backtestId,
        status: 'PENDING',
        message: 'Backtest created. Run worker to process.',
        hint: 'docker exec polypaper-worker python -m backtest.runner --id ' + backtestId
      };
    } finally {
      client.release();
    }
  });

  // Run Monte Carlo robustness on existing backtest
  app.post<{ Params: { id: string } }>('/backtests/:id/monte-carlo', async (request) => {
    const { id } = request.params;
    const body = request.body as any;
    
    const {
      num_simulations = 1000,
      block_size = 5,
      ruin_threshold = 0.5
    } = body || {};
    
    const client = await db.connect();
    try {
      // Get backtest
      const result = await client.query(
        'SELECT * FROM backtests WHERE id = $1',
        [id]
      );
      
      if (result.rows.length === 0) {
        return { error: 'Backtest not found' };
      }
      
      const backtest = result.rows[0];
      
      if (!backtest.equity_curve || backtest.equity_curve.length === 0) {
        return { error: 'No equity curve available for Monte Carlo' };
      }
      
      // Extract equity values
      const equityValues = backtest.equity_curve.map((e: any) => e.equity);
      
      // In production, this would be done by worker
      // For now, return a placeholder
      return {
        backtest_id: id,
        status: 'PENDING',
        message: 'Monte Carlo analysis queued',
        params: {
          num_simulations,
          block_size,
          ruin_threshold
        },
        hint: 'Run worker to process: docker exec polypaper-worker python -m backtest.monte_carlo --id ' + id
      };
    } finally {
      client.release();
    }
  });

  // Delete backtest
  app.delete<{ Params: { id: string } }>('/backtests/:id', async (request) => {
    const { id } = request.params;
    
    const client = await db.connect();
    try {
      const result = await client.query(
        'DELETE FROM backtests WHERE id = $1 RETURNING id',
        [id]
      );
      
      if (result.rows.length === 0) {
        return { error: 'Backtest not found' };
      }
      
      return { deleted: true, id };
    } finally {
      client.release();
    }
  });
}
