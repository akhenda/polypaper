# Polypaper

Paper trading system for crypto markets with strategy engine.

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

- **Postgres** - Market data, orders, positions, strategy state
- **Redis** - Caching and pub/sub
- **API** (Node.js) - REST API at :3001
- **Web** (Next.js) - Dashboard at :3000
- **Worker** (Python) - Strategy runner loop

## Strategy Runner

The worker container runs a continuous loop:

1. Fetches current prices from Binance (public API)
2. Runs configured strategies on each interval
3. Executes paper trades (no real money)
4. Tracks positions, PnL, and strategy state

### Default Strategy: Late Entry

- Enters during favorable volatility conditions
- Position cap: $20 USD
- Take profit: 5%
- Stop loss: 3%
- Circuit breaker: 24h cooldown after 3 consecutive losses

### Configuration

Environment variables for the worker:

```bash
STRATEGY_INTERVAL_SECONDS=60  # How often to run
POSITION_CAP_USD=20           # Max position size
MAX_CONSECUTIVE_LOSSES=3      # Circuit breaker threshold
COOLDOWN_HOURS=24             # Cooldown period
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /accounts` | List accounts |
| `GET /positions` | List positions |
| `GET /orders` | List orders |
| `POST /strategies/activate` | Activate a strategy |

## Development

```bash
# Run in dev mode
docker compose up

# View worker logs
docker compose logs -f worker

# Rebuild after changes
docker compose up -d --build
```

## License

MIT
