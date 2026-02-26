import { Pool } from 'pg';
import dotenv from 'dotenv';
import { v4 as uuidv4 } from 'uuid';

dotenv.config();

const db = new Pool({
  connectionString: process.env.DATABASE_URL,
});

async function seed() {
  console.log('Seeding database...');
  
  try {
    // Insert default account if not exists
    const accountResult = await db.query(`
      INSERT INTO accounts (id, name, currency, initial_balance, current_balance)
      SELECT $1, $2, $3, $4, $4
      WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE name = 'Main Paper Account')
      RETURNING id
    `, [uuidv4(), 'Main Paper Account', 'USD', 10000]);
    
    if (accountResult.rows.length > 0) {
      console.log('Created default account');
    }

    // Insert default markets if not exist
    await db.query(`
      INSERT INTO markets (symbol, type, source, name, tick_size, min_quantity, metadata)
      VALUES 
        ('BTC-USD', 'CRYPTO', 'BINANCE', 'Bitcoin', 0.01, 0.0001, '{"coingecko_id": "bitcoin"}'),
        ('ETH-USD', 'CRYPTO', 'BINANCE', 'Ethereum', 0.01, 0.001, '{"coingecko_id": "ethereum"}')
      ON CONFLICT (symbol) DO NOTHING
    `);
    console.log('Markets seeded');

    // Insert sample candle data for BTC
    const btcMarket = await db.query(`SELECT id FROM markets WHERE symbol = 'BTC-USD'`);
    if (btcMarket.rows.length > 0) {
      const btcId = btcMarket.rows[0].id;
      const basePrice = 95000;
      
      // Insert some sample candles
      for (let i = 0; i < 24; i++) {
        const timestamp = new Date(Date.now() - (23 - i) * 60 * 60 * 1000);
        const variation = (Math.random() - 0.5) * 0.02;
        const open = basePrice * (1 + variation);
        const close = basePrice * (1 + variation + (Math.random() - 0.5) * 0.01);
        const high = Math.max(open, close) * (1 + Math.random() * 0.005);
        const low = Math.min(open, close) * (1 - Math.random() * 0.005);
        const volume = 1000 + Math.random() * 5000;
        
        await db.query(`
          INSERT INTO market_candles (market_id, interval, timestamp, open, high, low, close, volume)
          VALUES ($1, '1h', $2, $3, $4, $5, $6, $7)
          ON CONFLICT (market_id, interval, timestamp) DO NOTHING
        `, [btcId, timestamp, open, high, low, close, volume]);
      }
      console.log('Sample BTC candles seeded');
    }

    console.log('Seed complete!');
  } catch (err) {
    console.error('Seed error:', err);
    process.exit(1);
  } finally {
    await db.end();
  }
}

seed();
