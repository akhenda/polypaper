import Fastify from 'fastify';
import cors from '@fastify/cors';
import { Pool } from 'pg';
import Redis from 'ioredis';
import dotenv from 'dotenv';

dotenv.config();

// Database connection
export const db = new Pool({
  connectionString: process.env.DATABASE_URL,
});

// Redis connection
export const redis = new Redis(process.env.REDIS_URL || 'redis://localhost:6379');

// Fastify app
const app = Fastify({ logger: true });

// CORS
app.register(cors, { origin: true });

// Health check
app.get('/health', async () => ({ status: 'ok', timestamp: new Date().toISOString() }));

// Routes
import accountsRoutes from './routes/accounts.js';
import ordersRoutes from './routes/orders.js';
import positionsRoutes from './routes/positions.js';
import marketsRoutes from './routes/markets.js';
import strategiesRoutes from './routes/strategies.js';
import dashboardRoutes from './routes/dashboard.js';
import indicatorsRoutes from './routes/indicators.js';
import polymarketRoutes from './routes/polymarket.js';
import backtestsRoutes from './routes/backtests.js';

app.register(accountsRoutes, { prefix: '/api/v1/accounts' });
app.register(ordersRoutes, { prefix: '/api/v1/orders' });
app.register(positionsRoutes, { prefix: '/api/v1/positions' });
app.register(marketsRoutes, { prefix: '/api/v1/markets' });
app.register(strategiesRoutes, { prefix: '/api/v1/strategies' });
app.register(dashboardRoutes, { prefix: '/api/v1/dashboard' });
app.register(indicatorsRoutes, { prefix: '/api/v1' });
app.register(polymarketRoutes, { prefix: '/api/v1' });
app.register(backtestsRoutes, { prefix: '/api/v1' });

// Start server
const start = async () => {
  try {
    const port = parseInt(process.env.PORT || '3001', 10);
    const host = '0.0.0.0';
    await app.listen({ port, host });
    console.log(`API server running on http://${host}:${port}`);
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
};

start();
