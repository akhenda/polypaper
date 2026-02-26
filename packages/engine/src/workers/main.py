"""
Polypaper Strategy Runner Worker

Runs strategy loops for paper trading accounts.
Fetches market data, executes strategies, manages paper positions.
"""
import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, List

import psycopg2
from psycopg2.extras import RealDictCursor
import requests

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import MarketData, Position, Signal, SignalType
from strategies.examples.late_entry import LateEntryStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Environment config
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://polypaper:polypaper@localhost:5432/polypaper")
STRATEGY_INTERVAL_SECONDS = int(os.getenv("STRATEGY_INTERVAL_SECONDS", "60"))
POSITION_CAP_USD = Decimal(os.getenv("POSITION_CAP_USD", "20"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS", "24"))

# Binance API config
BINANCE_API_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_RATE_LIMIT_DELAY = 0.5  # Conservative delay between requests
BINANCE_TIMEOUT = 10
last_binance_request = 0

# Symbol mapping
BINANCE_SYMBOL_MAP = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
}


class BinanceRateLimitError(Exception):
    """Raised when Binance rate limits are hit."""
    pass


def get_db_connection():
    """Get database connection with dict cursor."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def fetch_binance_price(symbol: str) -> Optional[Decimal]:
    """
    Fetch current price from Binance public API.
    Implements rate limiting and exponential backoff.
    """
    global last_binance_request
    
    binance_symbol = BINANCE_SYMBOL_MAP.get(symbol)
    if not binance_symbol:
        logger.warning(f"No Binance mapping for {symbol}")
        return None
    
    # Rate limiting
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
                # Rate limited - respect Retry-After
                retry_after = int(resp.headers.get("Retry-After", 60))
                logger.warning(f"Binance rate limited, waiting {retry_after}s")
                time.sleep(retry_after)
                continue
            
            resp.raise_for_status()
            data = resp.json()
            price = Decimal(str(data["price"]))
            logger.debug(f"Fetched {symbol} price: {price}")
            return price
            
        except requests.exceptions.Timeout:
            logger.warning(f"Binance timeout for {symbol} (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.info(f"Retrying in {delay}s...")
                time.sleep(delay)
            else:
                log_error("binance", f"Timeout fetching {symbol}", None, {"symbol": symbol})
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Binance request error: {e}")
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.info(f"Retrying in {delay}s...")
                time.sleep(delay)
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
        logger.error(f"Failed to log error to DB: {e}")


def log_trade(account_id: str, order_id: str, position_id: str, action: str, details: dict):
    """Log trade action to trade_log table."""
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
    """Ensure at least one active account exists, return its ID."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check for active account
            cur.execute("SELECT id FROM accounts WHERE is_active = true LIMIT 1")
            row = cur.fetchone()
            if row:
                return str(row["id"])
            
            # Create default account if none exists
            logger.info("No active account found, creating default...")
            cur.execute("""
                INSERT INTO accounts (name, currency, initial_balance, current_balance, is_active)
                VALUES ('Main Paper Account', 'USD', 10000, 10000, true)
                RETURNING id
            """)
            conn.commit()
            row = cur.fetchone()
            return str(row["id"]) if row else None


def ensure_strategy_instance(account_id: str) -> Optional[str]:
    """Ensure strategy instance exists for late-entry-v1, return instance ID."""
    strategy_id = "late-entry-v1"
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check for existing instance
            cur.execute("""
                SELECT id FROM strategy_instances 
                WHERE account_id = %s AND strategy_id = %s AND is_active = true
            """, (account_id, strategy_id))
            row = cur.fetchone()
            if row:
                return str(row["id"])
            
            # Create new instance
            logger.info(f"Creating strategy instance for {strategy_id}")
            default_params = {
                "positionCapUsd": float(POSITION_CAP_USD),
                "volatilityThreshold": 0.015,
                "maxConsecutiveLosses": MAX_CONSECUTIVE_LOSSES,
                "cooldownHours": COOLDOWN_HOURS,
                "takeProfitPercent": 5.0,
                "stopLossPercent": 3.0,
            }
            cur.execute("""
                INSERT INTO strategy_instances (account_id, strategy_id, parameters, is_active)
                VALUES (%s, %s, %s, true)
                RETURNING id
            """, (account_id, strategy_id, json.dumps(default_params)))
            row = cur.fetchone()
            
            # Ensure strategy_state row exists
            cur.execute("""
                INSERT INTO strategy_state (account_id, strategy_id, consecutive_losses, total_trades, winning_trades, total_pnl)
                VALUES (%s, %s, 0, 0, 0, 0)
                ON CONFLICT (account_id, strategy_id) DO NOTHING
            """, (account_id, strategy_id))
            
            conn.commit()
            return str(row["id"]) if row else None


def get_market_id(symbol: str) -> Optional[str]:
    """Get market ID for a symbol."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM markets WHERE symbol = %s AND is_active = true", (symbol,))
            row = cur.fetchone()
            return str(row["id"]) if row else None


def get_or_create_candle(market_id: str, symbol: str) -> Optional[MarketData]:
    """
    Get latest candle or create one from current price.
    Returns MarketData object for strategy.
    """
    now_ms = int(time.time() * 1000)
    
    # Try to get latest candle
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT timestamp, open, high, low, close, volume 
                FROM market_candles 
                WHERE market_id = %s AND interval = '1m'
                ORDER BY timestamp DESC LIMIT 1
            """, (market_id,))
            row = cur.fetchone()
            
            if row:
                return MarketData(
                    symbol=symbol,
                    timestamp=int(row["timestamp"].timestamp() * 1000),
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=Decimal(str(row["volume"]))
                )
    
    # No candle - fetch price and create one
    price = fetch_binance_price(symbol)
    if price is None:
        return None
    
    # Insert candle (OHLC all same for snapshot)
    candle_time = datetime.utcnow().replace(second=0, microsecond=0)
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market_candles (market_id, interval, timestamp, open, high, low, close, volume)
                VALUES (%s, '1m', %s, %s, %s, %s, %s, 0)
                ON CONFLICT (market_id, interval, timestamp) DO UPDATE
                SET close = EXCLUDED.close
            """, (market_id, candle_time, price, price, price, price))
            conn.commit()
    
    logger.info(f"Created candle for {symbol} at {price}")
    
    return MarketData(
        symbol=symbol,
        timestamp=now_ms,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("0")
    )


def get_open_positions(account_id: str, market_id: str = None) -> List[Position]:
    """Get open positions as Position objects."""
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
            
            rows = cur.fetchall()
            return [
                Position(
                    symbol=row["symbol"],
                    side=row["side"],
                    quantity=Decimal(str(row["quantity"])),
                    avg_entry_price=Decimal(str(row["avg_entry_price"]))
                )
                for row in rows
            ]


def get_strategy_state(account_id: str) -> Dict[str, Any]:
    """Get strategy state from DB."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT consecutive_losses, last_loss_at, cooldown_until, total_trades, winning_trades, total_pnl
                FROM strategy_state
                WHERE account_id = %s AND strategy_id = 'late-entry-v1'
            """, (account_id,))
            row = cur.fetchone()
            if row:
                return {
                    "consecutive_losses": row["consecutive_losses"] or 0,
                    "last_loss_at": row["last_loss_at"],
                    "cooldown_until": row["cooldown_until"],
                    "total_trades": row["total_trades"] or 0,
                    "winning_trades": row["winning_trades"] or 0,
                    "total_pnl": float(row["total_pnl"] or 0),
                }
            return {
                "consecutive_losses": 0,
                "last_loss_at": None,
                "cooldown_until": None,
                "total_trades": 0,
                "winning_trades": 0,
                "total_pnl": 0,
            }


def update_strategy_state(account_id: str, state: Dict[str, Any]):
    """Update strategy state in DB."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE strategy_state 
                SET consecutive_losses = %s,
                    last_loss_at = %s,
                    cooldown_until = %s,
                    total_trades = %s,
                    winning_trades = %s,
                    total_pnl = %s,
                    updated_at = NOW()
                WHERE account_id = %s AND strategy_id = 'late-entry-v1'
            """, (
                state.get("consecutive_losses", 0),
                state.get("last_loss_at"),
                state.get("cooldown_until"),
                state.get("total_trades", 0),
                state.get("winning_trades", 0),
                state.get("total_pnl", 0),
                account_id
            ))
            conn.commit()


def execute_paper_order(account_id: str, market_id: str, signal: Signal, 
                        strategy_id: str, current_price: Decimal) -> bool:
    """
    Execute paper order - directly fills at current price.
    Updates orders, positions, accounts, and strategy_state.
    """
    now = datetime.utcnow()
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Create FILLED order
                cur.execute("""
                    INSERT INTO orders (account_id, market_id, strategy_id, side, type, quantity, price, 
                                       filled_quantity, avg_fill_price, status, filled_at)
                    VALUES (%s, %s, %s, %s, 'MARKET', %s, %s, %s, %s, 'FILLED', %s)
                    RETURNING id
                """, (
                    account_id, market_id, strategy_id,
                    "BUY" if signal.signal_type == SignalType.BUY else "SELL",
                    signal.quantity, current_price,
                    signal.quantity, current_price, now
                ))
                order_row = cur.fetchone()
                order_id = str(order_row["id"]) if order_row else None
                
                if signal.signal_type == SignalType.BUY:
                    # Open long position
                    cost = signal.quantity * current_price
                    
                    # Check balance
                    cur.execute("SELECT current_balance FROM accounts WHERE id = %s", (account_id,))
                    balance_row = cur.fetchone()
                    if not balance_row or Decimal(str(balance_row["current_balance"])) < cost:
                        logger.warning(f"Insufficient balance for order")
                        conn.rollback()
                        return False
                    
                    # Deduct from balance
                    cur.execute("""
                        UPDATE accounts SET current_balance = current_balance - %s, updated_at = NOW()
                        WHERE id = %s
                    """, (cost, account_id))
                    
                    # Create position
                    cur.execute("""
                        INSERT INTO positions (account_id, market_id, strategy_id, side, quantity, avg_entry_price, is_open)
                        VALUES (%s, %s, %s, 'LONG', %s, %s, true)
                        RETURNING id
                    """, (account_id, market_id, strategy_id, signal.quantity, current_price))
                    pos_row = cur.fetchone()
                    position_id = str(pos_row["id"]) if pos_row else None
                    
                    logger.info(f"Opened LONG position: {signal.quantity} @ {current_price}")
                    
                    log_trade(account_id, order_id, position_id, "OPEN_LONG", {
                        "symbol": signal.symbol,
                        "quantity": str(signal.quantity),
                        "price": str(current_price),
                        "reason": signal.reason
                    })
                
                elif signal.signal_type == SignalType.CLOSE_LONG:
                    # Close existing position
                    cur.execute("""
                        SELECT id, quantity, avg_entry_price 
                        FROM positions 
                        WHERE account_id = %s AND market_id = %s AND is_open = true
                    """, (account_id, market_id))
                    pos_row = cur.fetchone()
                    
                    if not pos_row:
                        logger.warning(f"No open position to close")
                        conn.rollback()
                        return False
                    
                    position_id = str(pos_row["id"])
                    entry_price = Decimal(str(pos_row["avg_entry_price"]))
                    quantity = Decimal(str(pos_row["quantity"]))
                    
                    # Calculate PnL
                    proceeds = quantity * current_price
                    cost_basis = quantity * entry_price
                    pnl = proceeds - cost_basis
                    
                    # Update position
                    cur.execute("""
                        UPDATE positions 
                        SET is_open = false, closed_at = %s, realized_pnl = %s
                        WHERE id = %s
                    """, (now, pnl, position_id))
                    
                    # Add to balance
                    cur.execute("""
                        UPDATE accounts SET current_balance = current_balance + %s, updated_at = NOW()
                        WHERE id = %s
                    """, (proceeds, account_id))
                    
                    # Update strategy state
                    is_win = pnl > 0
                    cur.execute("""
                        UPDATE strategy_state 
                        SET total_trades = total_trades + 1,
                            winning_trades = winning_trades + %s,
                            total_pnl = total_pnl + %s,
                            consecutive_losses = CASE WHEN %s THEN 0 ELSE consecutive_losses + 1 END,
                            last_loss_at = CASE WHEN %s THEN NULL ELSE NOW() END,
                            cooldown_until = CASE 
                                WHEN NOT %s AND consecutive_losses + 1 >= %s 
                                THEN NOW() + INTERVAL '%s hours' 
                                ELSE cooldown_until 
                            END,
                            updated_at = NOW()
                        WHERE account_id = %s AND strategy_id = %s
                    """, (
                        1 if is_win else 0,  # winning_trades increment
                        pnl,  # total_pnl increment
                        is_win,  # reset consecutive_losses?
                        is_win,  # clear last_loss_at?
                        is_win,  # check cooldown condition
                        MAX_CONSECUTIVE_LOSSES,
                        COOLDOWN_HOURS,
                        account_id, strategy_id
                    ))
                    
                    logger.info(f"Closed LONG position: {quantity} @ {current_price}, PnL: {pnl:.4f}")
                    
                    log_trade(account_id, order_id, position_id, "CLOSE_LONG", {
                        "symbol": signal.symbol,
                        "quantity": str(quantity),
                        "entry_price": str(entry_price),
                        "exit_price": str(current_price),
                        "pnl": str(pnl),
                        "is_win": is_win
                    })
                
                conn.commit()
                return True
                
    except Exception as e:
        logger.error(f"Failed to execute order: {e}")
        log_error("worker", f"Order execution failed: {e}", str(e), {
            "account_id": account_id,
            "market_id": market_id,
            "signal": str(signal.signal_type.value)
        })
        return False


def run_strategy_loop():
    """Main strategy execution loop."""
    logger.info("Starting strategy runner...")
    
    # Ensure account exists
    account_id = ensure_active_account()
    if not account_id:
        logger.error("No active account available")
        return
    
    logger.info(f"Using account: {account_id}")
    
    # Ensure strategy instance exists
    instance_id = ensure_strategy_instance(account_id)
    if not instance_id:
        logger.error("Failed to create strategy instance")
        return
    
    logger.info(f"Strategy instance: {instance_id}")
    
    # Get market IDs
    markets = {}
    for symbol in ["BTC-USD", "ETH-USD"]:
        market_id = get_market_id(symbol)
        if market_id:
            markets[symbol] = market_id
            logger.info(f"Market {symbol}: {market_id}")
    
    if not markets:
        logger.error("No markets available")
        return
    
    # Main loop
    logger.info(f"Starting main loop (interval: {STRATEGY_INTERVAL_SECONDS}s)")
    
    while True:
        try:
            cycle_start = time.time()
            
            # Get strategy state
            state = get_strategy_state(account_id)
            
            # Check cooldown
            if state.get("cooldown_until"):
                cooldown_until = state["cooldown_until"]
                if isinstance(cooldown_until, str):
                    cooldown_until = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00"))
                
                if cooldown_until and datetime.utcnow() < cooldown_until.replace(tzinfo=None):
                    logger.info(f"In cooldown until {cooldown_until}")
                    time.sleep(STRATEGY_INTERVAL_SECONDS)
                    continue
            
            # Create strategy instance with current state
            strategy = LateEntryStrategy({
                "positionCapUsd": float(POSITION_CAP_USD),
                "maxConsecutiveLosses": MAX_CONSECUTIVE_LOSSES,
                "cooldownHours": COOLDOWN_HOURS,
            }, state=state)
            
            # Check if circuit breaker is active
            if state.get("consecutive_losses", 0) >= MAX_CONSECUTIVE_LOSSES:
                logger.info(f"Circuit breaker active ({state['consecutive_losses']} losses)")
                time.sleep(STRATEGY_INTERVAL_SECONDS)
                continue
            
            # Run for each market
            for symbol, market_id in markets.items():
                # Get or create candle
                market_data = get_or_create_candle(market_id, symbol)
                if not market_data:
                    logger.warning(f"No market data for {symbol}")
                    continue
                
                # Get positions for this market
                positions = get_open_positions(account_id, market_id)
                
                # Run strategy
                signal = strategy.on_data(market_data, positions)
                
                if signal:
                    logger.info(f"Signal: {signal.signal_type.value} {signal.symbol} "
                               f"qty={signal.quantity} reason={signal.reason}")
                    
                    # Execute paper order
                    execute_paper_order(
                        account_id, market_id, signal, 
                        "late-entry-v1", market_data.close
                    )
                    
                    # Update strategy state from strategy instance
                    update_strategy_state(account_id, strategy.state)
            
            # Sleep for remainder of interval
            elapsed = time.time() - cycle_start
            sleep_time = max(1, STRATEGY_INTERVAL_SECONDS - elapsed)
            logger.debug(f"Cycle complete, sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in strategy loop: {e}")
            log_error("worker", f"Strategy loop error: {e}", str(e), {})
            time.sleep(STRATEGY_INTERVAL_SECONDS)


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Polypaper Strategy Worker Starting")
    logger.info(f"Interval: {STRATEGY_INTERVAL_SECONDS}s")
    logger.info(f"Position Cap: ${POSITION_CAP_USD}")
    logger.info(f"Max Losses: {MAX_CONSECUTIVE_LOSSES}")
    logger.info(f"Cooldown: {COOLDOWN_HOURS}h")
    logger.info("=" * 50)
    
    run_strategy_loop()
