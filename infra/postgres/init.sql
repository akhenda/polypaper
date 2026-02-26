-- Polypaper Database Schema
-- Paper trading system for Polymarket + Crypto

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Markets (crypto + prediction markets)
CREATE TABLE markets (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  symbol VARCHAR(50) UNIQUE NOT NULL,
  type VARCHAR(20) NOT NULL CHECK (type IN ('CRYPTO', 'PREDICTION')),
  source VARCHAR(20) NOT NULL,  -- BINANCE, POLYMARKET, etc.
  name VARCHAR(255) NOT NULL,
  tick_size DECIMAL(18,8) NOT NULL DEFAULT 0.01,
  min_quantity DECIMAL(18,8) NOT NULL DEFAULT 0.0001,
  metadata JSONB DEFAULT '{}',  -- prediction market expiry, etc.
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Market data (OHLCV)
CREATE TABLE market_candles (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  market_id UUID NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  interval VARCHAR(10) NOT NULL,  -- 1m, 5m, 1h, 1d
  timestamp TIMESTAMPTZ NOT NULL,
  open DECIMAL(18,8) NOT NULL,
  high DECIMAL(18,8) NOT NULL,
  low DECIMAL(18,8) NOT NULL,
  close DECIMAL(18,8) NOT NULL,
  volume DECIMAL(18,8) NOT NULL,
  UNIQUE(market_id, interval, timestamp)
);
CREATE INDEX idx_candles_market_time ON market_candles(market_id, timestamp DESC);

-- Paper accounts
CREATE TABLE accounts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name VARCHAR(100) NOT NULL,
  currency VARCHAR(10) NOT NULL DEFAULT 'USD',
  initial_balance DECIMAL(18,8) NOT NULL,
  current_balance DECIMAL(18,8) NOT NULL,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Orders
CREATE TABLE orders (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES accounts(id),
  market_id UUID NOT NULL REFERENCES markets(id),
  strategy_id VARCHAR(100),  -- optional
  side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
  type VARCHAR(10) NOT NULL CHECK (type IN ('MARKET', 'LIMIT', 'STOP')),
  quantity DECIMAL(18,8) NOT NULL,
  price DECIMAL(18,8),       -- for LIMIT/STOP
  filled_quantity DECIMAL(18,8) DEFAULT 0,
  avg_fill_price DECIMAL(18,8),
  status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'OPEN', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'REJECTED')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  filled_at TIMESTAMPTZ
);
CREATE INDEX idx_orders_account ON orders(account_id);
CREATE INDEX idx_orders_status ON orders(status);

-- Positions
CREATE TABLE positions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES accounts(id),
  market_id UUID NOT NULL REFERENCES markets(id),
  strategy_id VARCHAR(100),
  side VARCHAR(10) NOT NULL CHECK (side IN ('LONG', 'SHORT', 'YES', 'NO')),
  quantity DECIMAL(18,8) NOT NULL,
  avg_entry_price DECIMAL(18,8) NOT NULL,
  realized_pnl DECIMAL(18,8) DEFAULT 0,
  is_open BOOLEAN DEFAULT true,
  opened_at TIMESTAMPTZ DEFAULT NOW(),
  closed_at TIMESTAMPTZ
);
CREATE INDEX idx_positions_account ON positions(account_id);
CREATE INDEX idx_positions_open ON positions(is_open);
-- Partial unique index for open positions (one open position per account/market)
CREATE UNIQUE INDEX idx_positions_unique_open ON positions(account_id, market_id) WHERE is_open = true;

-- Strategy instances (active strategies per account)
CREATE TABLE strategy_instances (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES accounts(id),
  strategy_id VARCHAR(100) NOT NULL,
  parameters JSONB DEFAULT '{}',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strategy state (consecutive losses, cooldown, etc.)
CREATE TABLE strategy_state (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES accounts(id),
  strategy_id VARCHAR(100) NOT NULL,
  consecutive_losses INT DEFAULT 0,
  last_loss_at TIMESTAMPTZ,
  cooldown_until TIMESTAMPTZ,
  total_trades INT DEFAULT 0,
  winning_trades INT DEFAULT 0,
  total_pnl DECIMAL(18,8) DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id, strategy_id)
);

-- Backtest results
CREATE TABLE backtests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  strategy_id VARCHAR(100) NOT NULL,
  parameters JSONB DEFAULT '{}',
  market_ids UUID[] NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  initial_capital DECIMAL(18,8) NOT NULL,
  final_capital DECIMAL(18,8),
  total_return DECIMAL(10,4),
  sharpe_ratio DECIMAL(10,4),
  max_drawdown DECIMAL(10,4),
  win_rate DECIMAL(10,4),
  trade_count INT,
  equity_curve JSONB,
  trades JSONB,
  status VARCHAR(20) DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

-- Audit log for all trades
CREATE TABLE trade_log (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES accounts(id),
  order_id UUID REFERENCES orders(id),
  position_id UUID REFERENCES positions(id),
  action VARCHAR(50) NOT NULL,
  details JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Error log for debugging
CREATE TABLE error_log (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source VARCHAR(100) NOT NULL,  -- api, worker, strategy, etc.
  message TEXT NOT NULL,
  stack_trace TEXT,
  context JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default paper account
INSERT INTO accounts (id, name, currency, initial_balance, current_balance)
VALUES (uuid_generate_v4(), 'Main Paper Account', 'USD', 10000, 10000);

-- Insert default markets
INSERT INTO markets (symbol, type, source, name, tick_size, min_quantity, metadata) VALUES
('BTC-USD', 'CRYPTO', 'BINANCE', 'Bitcoin', 0.01, 0.0001, '{"coingecko_id": "bitcoin"}'),
('ETH-USD', 'CRYPTO', 'BINANCE', 'Ethereum', 0.01, 0.001, '{"coingecko_id": "ethereum"}');

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at trigger to relevant tables
CREATE TRIGGER update_markets_updated_at BEFORE UPDATE ON markets FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_accounts_updated_at BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_strategy_instances_updated_at BEFORE UPDATE ON strategy_instances FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_strategy_state_updated_at BEFORE UPDATE ON strategy_state FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
