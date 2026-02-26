# Polypaper

Paper trading system for crypto markets with multi-strategy engine.

## Quick Start

```bash
# Start all services
docker compose up -d --build

# Check health
curl localhost:3001/health

# Open dashboard
open http://localhost:3000
```

## Architecture

- **Postgres** - Market data, orders, positions, strategy state, indicators
- **Redis** - Caching and pub/sub
- **API** (Node.js) - REST API at :3001
- **Web** (Next.js) - Dashboard at :3000
- **Worker** (Python) - Multi-strategy runner loop

## Strategies (Phase 2A)

| Strategy | ID | Interval | Description |
|----------|-------|----------|-------------|
| Late Entry | `late-entry-v1` | 1m | Volatility-based entry with circuit breaker |
| Trend Following | `trend-following-v1` | 4h | ADX-confirmed trend trading with trailing stops |
| Mean Reversion | `mean-reversion-v1` | 15m | Bollinger Bands mean reversion |

### Strategy Parameters

Each strategy respects:
- `positionCapUsd` - Maximum position size (default: $20)
- `maxConsecutiveLosses` - Circuit breaker threshold (default: 3)
- `cooldownHours` - Cooldown after circuit breaker (default: 24h)

### Configuring Strategies

Update `packages/engine/src/workers/main.py` in `ensure_strategy_instances()`:

```python
strategies_config = [
    {
        "strategy_id": "late-entry-v1",
        "interval_minutes": 1,
        "parameters": {
            "positionCapUsd": 50,  # Increase position size
            "volatilityThreshold": 0.02,  # Higher volatility requirement
            ...
        }
    },
    ...
]
```

## Regime Filters (Phase 2B)

### ADX (Average Directional Index)
- Measures trend strength
- `ADX > 25` = strong trend
- `ADX < 20` = weak/no trend
- Used by Trend Following strategy

### Bollinger Bands
- 20-period SMA with 2 standard deviations
- Band width indicates volatility
- `width < 4%` = squeeze (avoid trading)
- `width > 8%` = expansion (high volatility)
- Used by Mean Reversion strategy

## Backtesting (Phase 2C)

Run backtests from the worker container:

```bash
# Enter worker container
docker compose exec worker bash

# Run backtest
python -m backtest.runner \
  --strategy late-entry-v1 \
  --market <market-id> \
  --start 2026-01-01 \
  --end 2026-02-26 \
  --save
```

Or programmatically:

```python
from backtest import run_backtest, save_backtest_result

result = run_backtest(
    strategy_id="late-entry-v1",
    parameters={"positionCapUsd": 50},
    market_id="<uuid>",
    start_date=datetime(2026, 1, 1),
    end_date=datetime(2026, 2, 26),
)

print(f"Return: {result.total_return:.2f}%")
print(f"Win Rate: {result.win_rate:.1f}%")
print(f"Max Drawdown: {result.max_drawdown:.2f}%")
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /accounts` | List accounts |
| `GET /positions` | List positions |
| `GET /orders` | List orders |
| `GET /strategies` | List strategy instances |
| `GET /indicators?market_id=<id>` | Get latest indicators |

## Database Schema

### strategy_state
Per-strategy tracking:
- `consecutive_losses`, `cooldown_until`
- `total_trades`, `winning_trades`, `total_losses`
- `total_pnl`, `max_drawdown`

### market_indicators
Latest indicator values:
- `adx`, `adx_trend`
- `bb_upper`, `bb_middle`, `bb_lower`, `bb_width`

### backtests
Backtest results:
- `strategy_id`, `parameters`, `start_date`, `end_date`
- `total_return`, `sharpe_ratio`, `max_drawdown`, `win_rate`
- `equity_curve`, `trades`

## Development

```bash
# Run in dev mode
docker compose up

# View worker logs
docker compose logs -f worker

# Rebuild after changes
docker compose up -d --build
```

## Configuration

Environment variables (in docker-compose.yml):

```bash
STRATEGY_INTERVAL_SECONDS=60  # Default tick interval
POSITION_CAP_USD=20           # Default position cap
MAX_CONSECUTIVE_LOSSES=3      # Circuit breaker
COOLDOWN_HOURS=24             # Cooldown period
```

## License

MIT
