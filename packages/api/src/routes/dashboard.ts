import { FastifyInstance } from 'fastify';
import { db } from '../index.js';

export default async function dashboardRoutes(app: FastifyInstance) {
  // Main dashboard data
  app.get<{ Querystring: { accountId?: string } }>('/', async (request) => {
    const { accountId } = request.query;
    
    // Get first active account if not specified
    let targetAccountId = accountId;
    if (!targetAccountId) {
      const accountResult = await db.query(`
        SELECT id FROM accounts WHERE is_active = true ORDER BY created_at LIMIT 1
      `);
      if (accountResult.rows.length === 0) {
        return { error: 'No active accounts' };
      }
      targetAccountId = accountResult.rows[0].id;
    }

    // Get account info
    const accountResult = await db.query(`
      SELECT * FROM accounts WHERE id = $1
    `, [targetAccountId]);
    const account = accountResult.rows[0];

    // Get open positions with unrealized PnL
    const positionsResult = await db.query(`
      SELECT p.*, m.symbol, m.name as market_name
      FROM positions p
      JOIN markets m ON p.market_id = m.id
      WHERE p.account_id = $1 AND p.is_open = true
    `, [targetAccountId]);

    // Calculate equity and unrealized PnL
    let unrealizedPnl = 0;
    const positions = await Promise.all(positionsResult.rows.map(async (pos) => {
      const priceResult = await db.query(`
        SELECT close as price FROM market_candles
        WHERE market_id = $1 ORDER BY timestamp DESC LIMIT 1
      `, [pos.market_id]);
      
      const currentPrice = priceResult.rows[0]?.price || pos.avg_entry_price;
      const pnl = (parseFloat(currentPrice) - parseFloat(pos.avg_entry_price)) * parseFloat(pos.quantity);
      unrealizedPnl += pnl;
      
      return {
        ...pos,
        currentPrice,
        unrealizedPnl: pnl
      };
    }));

    const equity = parseFloat(account.current_balance) + unrealizedPnl;
    const totalPnl = equity - parseFloat(account.initial_balance);

    // Get trade stats
    const statsResult = await db.query(`
      SELECT 
        COUNT(*) as total_trades,
        COUNT(CASE WHEN p.realized_pnl > 0 THEN 1 END) as winning_trades,
        COALESCE(SUM(p.realized_pnl), 0) as total_realized_pnl
      FROM positions p
      WHERE p.account_id = $1 AND p.is_open = false
    `, [targetAccountId]);

    const stats = statsResult.rows[0];
    const totalTrades = parseInt(stats.total_trades) || 0;
    const winningTrades = parseInt(stats.winning_trades) || 0;
    const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;

    // Get strategy instances with performance
    const strategiesResult = await db.query(`
      SELECT si.*, ss.consecutive_losses, ss.cooldown_until, ss.total_trades, ss.winning_trades, ss.total_pnl
      FROM strategy_instances si
      LEFT JOIN strategy_state ss ON si.account_id = ss.account_id AND si.strategy_id = ss.strategy_id
      WHERE si.account_id = $1 AND si.is_active = true
    `, [targetAccountId]);

    const strategies = strategiesResult.rows.map(s => ({
      id: s.strategy_id,
      consecutiveLosses: s.consecutive_losses || 0,
      cooldownUntil: s.cooldown_until,
      totalTrades: s.total_trades || 0,
      winningTrades: s.winning_trades || 0,
      winRate: s.total_trades > 0 ? (s.winning_trades / s.total_trades) * 100 : 0,
      totalPnl: s.total_pnl || 0,
      isActive: s.is_active
    }));

    // Get recent trades
    const recentTradesResult = await db.query(`
      SELECT o.*, m.symbol, m.name as market_name
      FROM orders o
      JOIN markets m ON o.market_id = m.id
      WHERE o.account_id = $1 AND o.status = 'FILLED'
      ORDER BY o.created_at DESC
      LIMIT 20
    `, [targetAccountId]);

    // Get error log
    const errorLogResult = await db.query(`
      SELECT * FROM error_log ORDER BY created_at DESC LIMIT 50
    `);

    return {
      account: {
        id: account.id,
        name: account.name,
        currency: account.currency,
        initialBalance: parseFloat(account.initial_balance),
        currentBalance: parseFloat(account.current_balance),
        equity,
        totalPnl,
        unrealizedPnl
      },
      stats: {
        totalTrades,
        winningTrades,
        winRate,
        totalRealizedPnl: parseFloat(stats.total_realized_pnl)
      },
      positions,
      strategies,
      recentTrades: recentTradesResult.rows,
      errorLog: errorLogResult.rows
    };
  });
}
