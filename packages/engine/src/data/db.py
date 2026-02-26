"""Database client and helpers."""
import os
from decimal import Decimal
from typing import Optional, List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://polypaper:polypaper@localhost:5432/polypaper")


def get_connection():
    """Get a database connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_active_accounts() -> List[Dict[str, Any]]:
    """Get all active paper accounts."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, currency, initial_balance, current_balance
                FROM accounts WHERE is_active = true
            """)
            return cur.fetchall()


def get_markets() -> List[Dict[str, Any]]:
    """Get all active markets."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, symbol, type, source, name, tick_size, min_quantity, metadata
                FROM markets WHERE is_active = true
            """)
            return cur.fetchall()


def get_latest_price(market_id: str) -> Optional[Decimal]:
    """Get latest price for a market."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT close FROM market_candles
                WHERE market_id = %s ORDER BY timestamp DESC LIMIT 1
            """, (market_id,))
            row = cur.fetchone()
            return Decimal(str(row["close"])) if row else None


def save_candle(market_id: str, interval: str, timestamp: int, 
                open_price: Decimal, high: Decimal, low: Decimal, 
                close: Decimal, volume: Decimal):
    """Save a candle to the database."""
    from datetime import datetime
    ts = datetime.fromtimestamp(timestamp / 1000)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market_candles (market_id, interval, timestamp, open, high, low, close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (market_id, interval, timestamp) DO UPDATE
                SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                    close = EXCLUDED.close, volume = EXCLUDED.volume
            """, (market_id, interval, ts, open_price, high, low, close, volume))
            conn.commit()


def get_open_positions(account_id: str) -> List[Dict[str, Any]]:
    """Get all open positions for an account."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.*, m.symbol, m.source
                FROM positions p
                JOIN markets m ON p.market_id = m.id
                WHERE p.account_id = %s AND p.is_open = true
            """, (account_id,))
            return cur.fetchall()


def get_strategy_state(account_id: str, strategy_id: str) -> Dict[str, Any]:
    """Get strategy state for an account."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM strategy_state
                WHERE account_id = %s AND strategy_id = %s
            """, (account_id, strategy_id))
            row = cur.fetchone()
            return dict(row) if row else {}


def update_strategy_state(account_id: str, strategy_id: str, **kwargs):
    """Update strategy state."""
    import json
    with get_connection() as conn:
        with conn.cursor() as cur:
            set_clauses = ", ".join(f"{k} = %s" for k in kwargs.keys())
            values = list(kwargs.values()) + [account_id, strategy_id]
            cur.execute(f"""
                UPDATE strategy_state SET {set_clauses}
                WHERE account_id = %s AND strategy_id = %s
            """, values)
            conn.commit()


def get_active_strategy_instances(account_id: str) -> List[Dict[str, Any]]:
    """Get active strategy instances for an account."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM strategy_instances
                WHERE account_id = %s AND is_active = true
            """, (account_id,))
            return cur.fetchall()


def create_order(account_id: str, market_id: str, strategy_id: str,
                 side: str, order_type: str, quantity: Decimal, 
                 price: Optional[Decimal]) -> Optional[str]:
    """Create an order in the database."""
    import uuid
    order_id = str(uuid.uuid4())
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO orders (id, account_id, market_id, strategy_id, side, type, quantity, price, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                RETURNING id
            """, (order_id, account_id, market_id, strategy_id, side, order_type, quantity, price))
            row = cur.fetchone()
            conn.commit()
            return row["id"] if row else None


def log_error(source: str, message: str, stack_trace: str = None, context: dict = None):
    """Log an error to the database."""
    import json
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO error_log (source, message, stack_trace, context)
                VALUES (%s, %s, %s, %s)
            """, (source, message, stack_trace, json.dumps(context or {})))
            conn.commit()
