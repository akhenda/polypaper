"""
Polymarket Sync Worker

Periodically syncs Polymarket markets and prices.
- Discovers active markets from Gamma API
- Stores them in the markets table
- Fetches mid prices from CLOB and creates synthetic candles
"""
import os
import sys
import time
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.polymarket_gamma import discover_active_markets, extract_market_info
from providers.polymarket_clob import get_mid_price, fetch_orderbook, get_spread

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://polypaper:polypaper@localhost:5432/polypaper")

# Sync intervals
MARKET_DISCOVERY_INTERVAL = 3600  # Discover new markets every hour
PRICE_SYNC_INTERVAL = 60  # Fetch prices every minute


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def generate_symbol(market_info: Dict) -> str:
    """Generate a stable symbol for a Polymarket market."""
    slug = market_info.get("slug", "unknown")
    slug = slug.replace("-", "_").replace(" ", "_")[:30]
    
    # Include outcome index for multi-outcome markets
    outcomes = market_info.get("outcomes", [])
    if len(outcomes) > 1:
        return f"POLY:{slug}:YES"
    
    return f"POLY:{slug}"


def upsert_market(market_info: Dict) -> Optional[str]:
    """
    Insert or update a market in the database.
    
    Returns the market UUID if successful.
    """
    symbol = generate_symbol(market_info)
    market_id = market_info.get("market_id")
    
    if not market_id:
        return None
    
    # Prepare metadata
    metadata = {
        "polymarket_id": market_id,
        "event_id": market_info.get("event_id"),
        "event_slug": market_info.get("event_slug"),
        "question": market_info.get("question"),
        "outcomes": market_info.get("outcomes", []),
        "token_ids": market_info.get("token_ids", []),
        "end_date": market_info.get("end_date"),
        "image": market_info.get("image"),
        "description": market_info.get("description"),
        "volume": market_info.get("volume"),
    }
    
    # Get first token ID for price fetching
    token_ids = market_info.get("token_ids", [])
    first_token = token_ids[0] if token_ids else None
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check if market exists
            cur.execute(
                "SELECT id FROM markets WHERE symbol = %s",
                (symbol,)
            )
            existing = cur.fetchone()
            
            if existing:
                # Update existing market
                cur.execute("""
                    UPDATE markets 
                    SET metadata = %s, 
                        is_active = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                """, (json.dumps(metadata), market_info.get("active", True), existing["id"]))
                conn.commit()
                return str(existing["id"])
            else:
                # Insert new market
                cur.execute("""
                    INSERT INTO markets (symbol, name, type, source, tick_size, min_quantity, metadata, is_active)
                    VALUES (%s, %s, 'PREDICTION', 'POLYMARKET', 0.01, 1, %s, %s)
                    RETURNING id
                """, (
                    symbol,
                    market_info.get("question", symbol)[:200],
                    json.dumps(metadata),
                    market_info.get("active", True)
                ))
                row = cur.fetchone()
                conn.commit()
                
                if row:
                    logger.info(f"Inserted new market: {symbol}")
                    return str(row["id"])
    
    return None


def get_polymarket_markets() -> List[Dict]:
    """Get all Polymarket markets from database."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, symbol, metadata, is_active
                FROM markets 
                WHERE source = 'POLYMARKET' AND is_active = true
            """)
            return cur.fetchall()


def insert_price_candle(market_id: str, price: Decimal, volume: Decimal = Decimal("0")):
    """Insert a synthetic 1m candle for a prediction market."""
    candle_time = datetime.utcnow().replace(second=0, microsecond=0)
    
    # Price is in 0-1 range for prediction markets, scale to cents for consistency
    # Actually, let's keep it as-is since it represents probability
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market_candles (market_id, interval, timestamp, open, high, low, close, volume)
                VALUES (%s, '1m', %s, %s, %s, %s, %s, %s)
                ON CONFLICT (market_id, interval, timestamp) DO UPDATE SET
                    close = EXCLUDED.close,
                    high = GREATEST(market_candles.high, EXCLUDED.high),
                    low = LEAST(market_candles.low, EXCLUDED.low)
            """, (market_id, candle_time, price, price, price, price, volume))
            conn.commit()


def sync_markets():
    """Discover and sync all active Polymarket markets."""
    logger.info("Starting Polymarket market discovery...")
    
    try:
        markets = discover_active_markets(max_markets=100)
        
        synced_count = 0
        for market_info in markets:
            market_uuid = upsert_market(market_info)
            if market_uuid:
                synced_count += 1
        
        logger.info(f"Synced {synced_count}/{len(markets)} Polymarket markets")
        return synced_count
        
    except Exception as e:
        logger.error(f"Failed to sync markets: {e}")
        return 0


def sync_prices():
    """Fetch and store prices for all active Polymarket markets."""
    markets = get_polymarket_markets()
    
    if not markets:
        logger.debug("No Polymarket markets to sync prices for")
        return
    
    updated_count = 0
    
    for market in markets:
        market_id = str(market["id"])
        metadata = market.get("metadata", {}) or {}
        token_ids = metadata.get("token_ids", [])
        
        if not token_ids:
            continue
        
        # Fetch price for first outcome token
        first_token = token_ids[0]
        price = get_mid_price(first_token)
        
        if price is not None:
            insert_price_candle(market_id, price)
            updated_count += 1
            logger.debug(f"Updated price for {market['symbol']}: {price}")
    
    logger.info(f"Updated prices for {updated_count}/{len(markets)} Polymarket markets")


def run_polymarket_sync():
    """Main sync loop."""
    logger.info("=" * 60)
    logger.info("Polymarket Sync Worker Starting")
    logger.info(f"Market discovery interval: {MARKET_DISCOVERY_INTERVAL}s")
    logger.info(f"Price sync interval: {PRICE_SYNC_INTERVAL}s")
    logger.info("=" * 60)
    
    last_discovery = 0
    
    while True:
        try:
            now = time.time()
            
            # Run market discovery periodically
            if now - last_discovery >= MARKET_DISCOVERY_INTERVAL:
                sync_markets()
                last_discovery = now
            
            # Run price sync every cycle
            sync_prices()
            
            # Sleep until next price sync
            time.sleep(PRICE_SYNC_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Sync loop error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    run_polymarket_sync()
