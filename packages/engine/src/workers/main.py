"""
Polypaper Strategy Runner Worker (Phase 2.1)

Event-driven multi-timeframe strategy runner.
- Maintains candles for 1m, 15m, 4h intervals
- Computes indicators only when new candles are created
- Strategies use candles aligned to their declared timeframe
"""
import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

import psycopg2
from psycopg2.extras import RealDictCursor
import requests

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import MarketData, Position, Signal, SignalType
from strategies import STRATEGY_REGISTRY
from indicators.adx import calculate_adx, get_trend_direction
from indicators.bollinger import calculate_bollinger_bands
from indicators.rsi import calculate_rsi
from data.candle_aggregator import aggregate_all_timeframes, get_bucket_start

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Environment config
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://polypaper:polypaper@localhost:5432/polypaper")
POSITION_CAP_USD = Decimal(os.getenv("POSITION_CAP_USD", "20"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS", "24"))

# Binance API config
BINANCE_API_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_RATE_LIMIT_DELAY = 0.5
BINANCE_TIMEOUT = 10
last_binance_request = 0

# Symbol mapping
BINANCE_SYMBOL_MAP = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
}

# Strategy to interval mapping
STRATEGY_INTERVALS = {
    "late-entry-v1": "1m",
    "mean-reversion-v1": "15m",
    "trend-following-v1": "4h",
}


@dataclass
class StrategyInstance:
    """Runtime strategy instance with state."""
    id: str
    account_id: str
    strategy_id: str
    parameters: Dict[str, Any]
    interval: str  # Candle interval (1m, 15m, 4h)
    interval_seconds: int  # How often to run strategy
    last_run: Optional[datetime]
    last_candle_time: Optional[datetime]
    state: Dict[str, Any]
    strategy_obj: Any


def get_db_connection():
    """Get database connection with dict cursor."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def fetch_binance_price(symbol: str) -> Optional[Decimal]:
    """Fetch current price from Binance with rate limiting."""
    global last_binance_request
    
    binance_symbol = BINANCE_SYMBOL_MAP.get(symbol)
    if not binance_symbol:
        logger.warning(f"No Binance mapping for {symbol}")
        return None
    
    elapsed = time.time() - last_binance_request
    if elapsed < BINANCE_RATE_LIMIT_DELAY:
        time.sleep(BINANCE_RATE_LIMIT_DELAY - elapsed)
    
    max_retries = 3
    base_delay = 1
    
    for attempt in range(max_retries):
        try:
            last_binance_request = time.time()
            resp = requests.get(
                BINANCE_API_URL,
                params={"symbol": binance_symbol},
                timeout=BINANCE_TIMEOUT
            )
            
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logger.warning(f"Binance 429, waiting {retry_after}s")
                time.sleep(retry_after)
                continue
            
            if resp.status_code == 418:
                logger.error("Binance 418 IP banned, waiting 5 minutes")
                time.sleep(300)
                continue
            
            resp.raise_for_status()
            data = resp.json()
            return Decimal(str(data["price"]))
            
        except requests.exceptions.Timeout:
            logger.warning(f"Binance timeout (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
            else:
                log_error("binance", f"Timeout", None, {"symbol": symbol})
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Binance error: {e}")
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
            else:
                log_error("binance", str(e), None, {"symbol": symbol})
                return None
    
    return None


def log_error(source: str, message: str, stack_trace: str = None, context: dict = None):
    """Log error to database."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO error_log (source, message, stack_trace, context)
                    VALUES (%s, %s, %s, %s)
                """, (source, message, stack_trace, json.dumps(context or {})))
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to log error: {e}")


def log_trade(account_id: str, order_id: str, position_id: str, action: str, details: dict):
    """Log trade action."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trade_log (account_id, order_id, position_id, action, details)
                    VALUES (%s, %s, %s, %s, %s)
                """, (account_id, order_id, position_id, action, json.dumps(details)))
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to log trade: {e}")


def ensure_active_account() -> Optional[str]:
    """Ensure at least one active account exists."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM accounts WHERE is_active = true LIMIT 1")
            row = cur.fetchone()
            if row:
                return str(row["id"])
            
            logger.info("Creating default account...")
            cur.execute("""
                INSERT INTO accounts (name, currency, initial_balance, current_balance, is_active)
                VALUES ('Main Paper Account', 'USD', 10000, 10000, true)
                RETURNING id
            """)
            conn.commit()
            row = cur.fetchone()
            return str(row["id"]) if row else None


def get_market_id(symbol: str) -> Optional[str]:
    """Get market ID for a symbol."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM markets WHERE symbol = %s AND is_active = true", (symbol,))
            row = cur.fetchone()
            return str(row["id"]) if row else None


def get_latest_candle_time(market_id: str, interval: str) -> Optional[datetime]:
    """Get the timestamp of the latest candle for an interval."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT MAX(timestamp) as latest
                FROM market_candles
                WHERE market_id = %s AND interval = %s
            """, (market_id, interval))
            row = cur.fetchone()
            return row["latest"] if row else None


def insert_1m_candle(market_id: str, symbol: str) -> tuple:
    """
    Insert a new 1m candle from current price.
    
    Returns: (candle_time, is_new) - the candle timestamp and whether it's new
    """
    price = fetch_binance_price(symbol)
    if price is None:
        return None, False
    
    candle_time = datetime.utcnow().replace(second=0, microsecond=0)
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check if candle already exists
            cur.execute("""
                SELECT 1 FROM market_candles
                WHERE market_id = %s AND interval = '1m' AND timestamp = %s
            """, (market_id, candle_time))
            exists = cur.fetchone()
            
            if exists:
                # Update existing candle
                cur.execute("""
                    UPDATE market_candles
                    SET close = %s, high = GREATEST(high, %s), low = LEAST(low, %s)
                    WHERE market_id = %s AND interval = '1m' AND timestamp = %s
                """, (price, price, price, market_id, candle_time))
                conn.commit()
                return candle_time, False
            
            # Insert new candle
            cur.execute("""
                INSERT INTO market_candles (market_id, interval, timestamp, open, high, low, close, volume)
                VALUES (%s, '1m', %s, %s, %s, %s, %s, 0)
            """, (market_id, candle_time, price, price, price, price))
            conn.commit()
            
            logger.info(f"New 1m candle for {symbol}: {price}")
            return candle_time, True


def aggregate_timeframes(market_id: str):
    """Aggregate 1m candles into higher timeframes."""
    results = aggregate_all_timeframes(DATABASE_URL, market_id)
    for tf, count in results.items():
        if count > 0:
            logger.info(f"Aggregated {count} {tf} candles")


def get_candle_history(market_id: str, interval: str, limit: int = 50) -> List[MarketData]:
    """Get historical candles for a specific interval."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT timestamp, open, high, low, close, volume 
                FROM market_candles 
                WHERE market_id = %s AND interval = %s
                ORDER BY timestamp DESC LIMIT %s
            """, (market_id, interval, limit))
            rows = cur.fetchall()
            
            rows = list(reversed(rows))
            
            return [
                MarketData(
                    symbol="",
                    timestamp=int(r["timestamp"].timestamp() * 1000),
                    open=Decimal(str(r["open"])),
                    high=Decimal(str(r["high"])),
                    low=Decimal(str(r["low"])),
                    close=Decimal(str(r["close"])),
                    volume=Decimal(str(r["volume"]))
                )
                for r in rows
            ]


def compute_and_save_indicators(market_id: str, interval: str, candle_time: datetime):
    """Compute indicators for a specific interval when new candle arrives."""
    # Get enough history for all indicators (ADX needs ~28 candles)
    candles = get_candle_history(market_id, interval, limit=50)
    
    if len(candles) < 28:
        logger.debug(f"Not enough candles ({len(candles)}) for {interval} indicators")
        return
    
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    
    # Calculate indicators
    adx_result = calculate_adx(highs, lows, closes, period=14)
    bb_result = calculate_bollinger_bands(closes, period=20, num_std=2.0)
    rsi_result = calculate_rsi(closes, period=14)
    
    adx_val = None
    adx_trend = None
    bb_upper = bb_middle = bb_lower = bb_width = None
    rsi_val = None
    
    if adx_result:
        adx, plus_di, minus_di = adx_result
        adx_val = float(adx)
        adx_trend = get_trend_direction(adx, plus_di, minus_di)
    
    if bb_result:
        upper, middle, lower, width = bb_result
        bb_upper = float(upper)
        bb_middle = float(middle)
        bb_lower = float(lower)
        bb_width = float(width)
    
    if rsi_result:
        rsi_val = float(rsi_result)
    
    # Save to database
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market_indicators 
                    (market_id, interval, timestamp, adx, adx_trend, 
                     bb_upper, bb_middle, bb_lower, bb_width, rsi)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (market_id, interval, timestamp) DO UPDATE SET
                    adx = EXCLUDED.adx,
                    adx_trend = EXCLUDED.adx_trend,
                    bb_upper = EXCLUDED.bb_upper,
                    bb_middle = EXCLUDED.bb_middle,
                    bb_lower = EXCLUDED.bb_lower,
                    bb_width = EXCLUDED.bb_width,
                    rsi = EXCLUDED.rsi
            """, (
                market_id, interval, candle_time,
                adx_val, adx_trend,
                bb_upper, bb_middle, bb_lower, bb_width, rsi_val
            ))
            conn.commit()
    
    logger.info(f"Computed {interval} indicators: ADX={adx_val}, BB_width={bb_width}, RSI={rsi_val}")


def get_latest_indicators(market_id: str, interval: str) -> Optional[Dict]:
    """Get latest indicators for a market/interval."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM market_indicators
                WHERE market_id = %s AND interval = %s
                ORDER BY timestamp DESC LIMIT 1
            """, (market_id, interval))
            row = cur.fetchone()
            return dict(row) if row else None


def get_open_positions(account_id: str, market_id: str = None) -> List[Position]:
    """Get open positions."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if market_id:
                cur.execute("""
                    SELECT p.*, m.symbol 
                    FROM positions p
                    JOIN markets m ON p.market_id = m.id
                    WHERE p.account_id = %s AND p.market_id = %s AND p.is_open = true
                """, (account_id, market_id))
            else:
                cur.execute("""
                    SELECT p.*, m.symbol 
                    FROM positions p
                    JOIN markets m ON p.market_id = m.id
                    WHERE p.account_id = %s AND p.is_open = true
                """, (account_id,))
            
            return [
                Position(
                    symbol=row["symbol"],
                    side=row["side"],
                    quantity=Decimal(str(row["quantity"])),
                    avg_entry_price=Decimal(str(row["avg_entry_price"]))
                )
                for row in cur.fetchall()
            ]


def get_strategy_state(instance_id: str) -> Dict[str, Any]:
    """Get strategy state by instance ID."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM strategy_state
                WHERE strategy_instance_id = %s
            """, (instance_id,))
            row = cur.fetchone()
            if row:
                return {
                    "consecutive_losses": row["consecutive_losses"] or 0,
                    "last_loss_at": row["last_loss_at"],
                    "cooldown_until": row["cooldown_until"],
                    "total_trades": row["total_trades"] or 0,
                    "winning_trades": row["winning_trades"] or 0,
                    "total_losses": row["total_losses"] or 0,
                    "total_pnl": float(row["total_pnl"] or 0),
                    "max_drawdown": float(row["max_drawdown"] or 0),
                }
            return {
                "consecutive_losses": 0,
                "last_loss_at": None,
                "cooldown_until": None,
                "total_trades": 0,
                "winning_trades": 0,
                "total_losses": 0,
                "total_pnl": 0,
                "max_drawdown": 0,
            }


def update_strategy_state(instance_id: str, state: Dict[str, Any]):
    """Update strategy state."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE strategy_state 
                SET consecutive_losses = %s,
                    last_loss_at = %s,
                    cooldown_until = %s,
                    total_trades = %s,
                    winning_trades = %s,
                    total_losses = %s,
                    total_pnl = %s,
                    max_drawdown = %s,
                    updated_at = NOW()
                WHERE strategy_instance_id = %s
            """, (
                state.get("consecutive_losses", 0),
                state.get("last_loss_at"),
                state.get("cooldown_until"),
                state.get("total_trades", 0),
                state.get("winning_trades", 0),
                state.get("total_losses", 0),
                state.get("total_pnl", 0),
                state.get("max_drawdown", 0),
                instance_id
            ))
            conn.commit()


def execute_paper_order(account_id: str, market_id: str, signal: Signal,
                        strategy_id: str, instance_id: str, current_price: Decimal) -> bool:
    """Execute paper order."""
    now = datetime.utcnow()
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if signal.signal_type == SignalType.BUY:
                    cost = signal.quantity * current_price
                    
                    cur.execute("SELECT current_balance FROM accounts WHERE id = %s", (account_id,))
                    balance_row = cur.fetchone()
                    if not balance_row or Decimal(str(balance_row["current_balance"])) < cost:
                        logger.warning(f"Insufficient balance")
                        return False
                    
                    # Deduct balance
                    cur.execute("""
                        UPDATE accounts SET current_balance = current_balance - %s
                        WHERE id = %s
                    """, (cost, account_id))
                    
                    # Create order
                    cur.execute("""
                        INSERT INTO orders (account_id, market_id, strategy_id, side, type, 
                                           quantity, price, filled_quantity, avg_fill_price, 
                                           status, filled_at)
                        VALUES (%s, %s, %s, 'BUY', 'MARKET', %s, %s, %s, %s, 'FILLED', %s)
                        RETURNING id
                    """, (account_id, market_id, strategy_id, signal.quantity, current_price,
                          signal.quantity, current_price, now))
                    order_row = cur.fetchone()
                    order_id = str(order_row["id"]) if order_row else None
                    
                    # Create position
                    cur.execute("""
                        INSERT INTO positions (account_id, market_id, strategy_id, side, 
                                              quantity, avg_entry_price, is_open)
                        VALUES (%s, %s, %s, 'LONG', %s, %s, true)
                        RETURNING id
                    """, (account_id, market_id, strategy_id, signal.quantity, current_price))
                    pos_row = cur.fetchone()
                    position_id = str(pos_row["id"]) if pos_row else None
                    
                    logger.info(f"Opened LONG: {signal.quantity} @ {current_price}")
                    log_trade(account_id, order_id, position_id, "OPEN_LONG", {
                        "symbol": signal.symbol,
                        "quantity": str(signal.quantity),
                        "price": str(current_price),
                        "strategy": strategy_id,
                        "reason": signal.reason
                    })
                    
                elif signal.signal_type == SignalType.CLOSE_LONG:
                    cur.execute("""
                        SELECT id, quantity, avg_entry_price 
                        FROM positions 
                        WHERE account_id = %s AND market_id = %s AND is_open = true
                    """, (account_id, market_id))
                    pos_row = cur.fetchone()
                    
                    if not pos_row:
                        logger.warning("No position to close")
                        return False
                    
                    position_id = str(pos_row["id"])
                    entry_price = Decimal(str(pos_row["avg_entry_price"]))
                    quantity = Decimal(str(pos_row["quantity"]))
                    
                    proceeds = quantity * current_price
                    pnl = proceeds - (quantity * entry_price)
                    
                    # Close position
                    cur.execute("""
                        UPDATE positions 
                        SET is_open = false, closed_at = %s, realized_pnl = %s
                        WHERE id = %s
                    """, (now, pnl, position_id))
                    
                    # Add balance
                    cur.execute("""
                        UPDATE accounts SET current_balance = current_balance + %s
                        WHERE id = %s
                    """, (proceeds, account_id))
                    
                    # Create order
                    cur.execute("""
                        INSERT INTO orders (account_id, market_id, strategy_id, side, type,
                                           quantity, price, filled_quantity, avg_fill_price,
                                           status, filled_at)
                        VALUES (%s, %s, %s, 'SELL', 'MARKET', %s, %s, %s, %s, 'FILLED', %s)
                        RETURNING id
                    """, (account_id, market_id, strategy_id, quantity, current_price,
                          quantity, current_price, now))
                    
                    is_win = pnl > 0
                    
                    # Update strategy state
                    cur.execute("""
                        UPDATE strategy_state 
                        SET total_trades = total_trades + 1,
                            winning_trades = winning_trades + %s,
                            total_losses = total_losses + %s,
                            total_pnl = total_pnl + %s,
                            consecutive_losses = CASE WHEN %s THEN 0 ELSE consecutive_losses + 1 END,
                            last_loss_at = CASE WHEN %s THEN NULL ELSE NOW() END,
                            cooldown_until = CASE 
                                WHEN NOT %s AND consecutive_losses + 1 >= %s 
                                THEN NOW() + INTERVAL '%s hours' 
                                ELSE cooldown_until 
                            END,
                            updated_at = NOW()
                        WHERE strategy_instance_id = %s
                    """, (
                        1 if is_win else 0,
                        0 if is_win else 1,
                        pnl,
                        is_win,
                        is_win,
                        is_win,
                        MAX_CONSECUTIVE_LOSSES,
                        COOLDOWN_HOURS,
                        instance_id
                    ))
                    
                    logger.info(f"Closed LONG: {quantity} @ {current_price}, PnL: {pnl:.4f}")
                    log_trade(account_id, None, position_id, "CLOSE_LONG", {
                        "symbol": signal.symbol,
                        "quantity": str(quantity),
                        "entry_price": str(entry_price),
                        "exit_price": str(current_price),
                        "pnl": str(pnl),
                        "is_win": is_win,
                        "strategy": strategy_id
                    })
                
                conn.commit()
                return True
                
    except Exception as e:
        logger.error(f"Order execution failed: {e}")
        log_error("worker", f"Order failed: {e}", str(e), {})
        return False


def ensure_strategy_instances(account_id: str) -> List[StrategyInstance]:
    """Create/return strategy instances with correct intervals."""
    strategies_config = [
        {
            "strategy_id": "late-entry-v1",
            "interval": "1m",
            "interval_minutes": 1,
            "parameters": {
                "positionCapUsd": float(POSITION_CAP_USD),
                "volatilityThreshold": 0.015,
                "maxConsecutiveLosses": MAX_CONSECUTIVE_LOSSES,
                "cooldownHours": COOLDOWN_HOURS,
                "takeProfitPercent": 5.0,
                "stopLossPercent": 3.0,
            }
        },
        {
            "strategy_id": "trend-following-v1",
            "interval": "4h",
            "interval_minutes": 240,
            "parameters": {
                "positionCapUsd": float(POSITION_CAP_USD),
                "adxThreshold": 25,
                "lookbackPeriod": 20,
                "trailingStopPercent": 2.0,
                "maxConsecutiveLosses": MAX_CONSECUTIVE_LOSSES,
                "cooldownHours": COOLDOWN_HOURS,
            }
        },
        {
            "strategy_id": "mean-reversion-v1",
            "interval": "15m",
            "interval_minutes": 15,
            "parameters": {
                "positionCapUsd": float(POSITION_CAP_USD),
                "bbPeriod": 20,
                "bbStdDev": 2.0,
                "minBandWidth": 5.0,
                "takeProfitPercent": 2.0,
                "stopLossPercent": 2.0,
                "maxConsecutiveLosses": MAX_CONSECUTIVE_LOSSES,
                "cooldownHours": 12,
            }
        },
    ]
    
    instances = []
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for config in strategies_config:
                strategy_id = config["strategy_id"]
                interval = config["interval"]
                
                # Check for existing instance
                cur.execute("""
                    SELECT id, parameters FROM strategy_instances 
                    WHERE account_id = %s AND strategy_id = %s AND is_active = true
                """, (account_id, strategy_id))
                row = cur.fetchone()
                
                if row:
                    instance_id = str(row["id"])
                    params = row["parameters"] or config["parameters"]
                else:
                    # Create new instance
                    cur.execute("""
                        INSERT INTO strategy_instances (account_id, strategy_id, parameters, is_active)
                        VALUES (%s, %s, %s, true)
                        RETURNING id
                    """, (account_id, strategy_id, json.dumps(config["parameters"])))
                    row = cur.fetchone()
                    instance_id = str(row["id"])
                    params = config["parameters"]
                    
                    # Create strategy_state with instance_id
                    cur.execute("""
                        INSERT INTO strategy_state 
                            (account_id, strategy_id, strategy_instance_id, 
                             consecutive_losses, total_trades, winning_trades, total_pnl)
                        VALUES (%s, %s, %s, 0, 0, 0, 0)
                        ON CONFLICT (account_id, strategy_id) 
                        DO UPDATE SET strategy_instance_id = EXCLUDED.strategy_instance_id
                    """, (account_id, strategy_id, instance_id))
                    
                    conn.commit()
                    logger.info(f"Created strategy instance: {strategy_id} ({interval})")
                
                # Get state
                state = get_strategy_state(instance_id)
                
                # Create strategy object
                strategy_class = STRATEGY_REGISTRY.get(strategy_id)
                if not strategy_class:
                    logger.warning(f"Unknown strategy: {strategy_id}")
                    continue
                
                strategy_obj = strategy_class(params, state=state)
                
                instances.append(StrategyInstance(
                    id=instance_id,
                    account_id=account_id,
                    strategy_id=strategy_id,
                    parameters=params,
                    interval=interval,
                    interval_seconds=config["interval_minutes"] * 60,
                    last_run=None,
                    last_candle_time=None,
                    state=state,
                    strategy_obj=strategy_obj
                ))
    
    return instances


def run_strategy(instance: StrategyInstance, symbol: str, market_id: str,
                 market_data: MarketData, candle_history: List[MarketData]):
    """Run a single strategy."""
    # Check cooldown
    if instance.state.get("cooldown_until"):
        cooldown_until = instance.state["cooldown_until"]
        if isinstance(cooldown_until, str):
            cooldown_until = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00"))
        
        if datetime.utcnow() < cooldown_until.replace(tzinfo=None):
            logger.debug(f"{instance.strategy_id} in cooldown")
            return
    
    # Check circuit breaker
    if instance.state.get("consecutive_losses", 0) >= MAX_CONSECUTIVE_LOSSES:
        logger.debug(f"{instance.strategy_id} circuit breaker active")
        return
    
    # Feed history to strategy
    strategy = instance.strategy_obj
    
    if hasattr(strategy, 'closes') and len(strategy.closes) == 0:
        for candle in candle_history:
            if hasattr(strategy, 'highs'):
                strategy.highs.append(candle.high)
            if hasattr(strategy, 'lows'):
                strategy.lows.append(candle.low)
            if hasattr(strategy, 'closes'):
                strategy.closes.append(candle.close)
            if hasattr(strategy, 'price_history'):
                strategy.price_history.append(candle.close)
    
    # Run strategy
    signal = strategy.on_data(market_data, get_open_positions(instance.account_id, market_id))
    
    if signal:
        logger.info(f"[{instance.strategy_id}] {signal.signal_type.value} {symbol} "
                   f"qty={signal.quantity:.6f} reason={signal.reason}")
        
        if execute_paper_order(instance.account_id, market_id, signal,
                              instance.strategy_id, instance.id, market_data.close):
            if hasattr(strategy, 'state'):
                instance.state = strategy.state
                update_strategy_state(instance.id, instance.state)


def run_event_driven_loop():
    """Main event-driven loop."""
    logger.info("Starting event-driven strategy runner...")
    
    # Ensure account
    account_id = ensure_active_account()
    if not account_id:
        logger.error("No active account")
        return
    
    logger.info(f"Account: {account_id}")
    
    # Get markets
    markets = {}
    for symbol in ["BTC-USD", "ETH-USD"]:
        market_id = get_market_id(symbol)
        if market_id:
            markets[symbol] = market_id
            logger.info(f"Market {symbol}: {market_id}")
    
    if not markets:
        logger.error("No markets")
        return
    
    # Create strategy instances
    instances = ensure_strategy_instances(account_id)
    logger.info(f"Strategies: {[(i.strategy_id, i.interval) for i in instances]}")
    
    # Track last processed candle per market
    last_candles: Dict[str, datetime] = {}
    
    logger.info("Starting main loop")
    
    while True:
        try:
            now = datetime.utcnow()
            
            # Process each market
            for symbol, market_id in markets.items():
                # Insert 1m candle
                candle_time, is_new = insert_1m_candle(market_id, symbol)
                
                if candle_time is None:
                    continue
                
                # If new 1m candle, aggregate and compute indicators
                if is_new:
                    # Aggregate to higher timeframes
                    aggregate_timeframes(market_id)
                    
                    # Compute 1m indicators
                    compute_and_save_indicators(market_id, "1m", candle_time)
                    
                    # Check if we completed higher timeframe buckets
                    if candle_time.minute == 0:
                        # Completed 1h bucket
                        compute_and_save_indicators(market_id, "1h", 
                            candle_time.replace(minute=0, second=0))
                    
                    if candle_time.minute % 15 == 0:
                        # Completed 15m bucket
                        compute_and_save_indicators(market_id, "15m",
                            candle_time.replace(minute=(candle_time.minute // 15) * 15, second=0))
                    
                    if candle_time.minute % 240 == 0:
                        # Completed 4h bucket
                        bucket_start = get_bucket_start(candle_time, 240)
                        compute_and_save_indicators(market_id, "4h", bucket_start)
                
                last_candles[market_id] = candle_time
                
                # Run strategies based on their interval
                for instance in instances:
                    # Check if strategy should run based on interval
                    if instance.last_run is None or \
                       (now - instance.last_run).total_seconds() >= instance.interval_seconds:
                        
                        # Get candles for strategy's interval
                        history = get_candle_history(market_id, instance.interval, limit=50)
                        
                        if not history:
                            continue
                        
                        # Get latest candle data for this interval
                        latest = history[-1] if history else None
                        if latest:
                            run_strategy(instance, symbol, market_id, latest, history)
                            instance.last_run = now
                            instance.last_candle_time = datetime.fromtimestamp(latest.timestamp / 1000)
            
            # Sleep until next minute boundary
            next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            sleep_seconds = (next_minute - datetime.utcnow()).total_seconds()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Loop error: {e}")
            log_error("worker", f"Loop error: {e}", str(e), {})
            time.sleep(5)


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Polypaper Worker (Phase 2.1) - Event-Driven")
    logger.info(f"Position Cap: ${POSITION_CAP_USD}")
    logger.info(f"Max Losses: {MAX_CONSECUTIVE_LOSSES}")
    logger.info(f"Cooldown: {COOLDOWN_HOURS}h")
    logger.info("=" * 60)
    
    run_event_driven_loop()
