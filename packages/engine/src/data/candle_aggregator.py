"""
Candle Aggregation Module

Aggregates 1m candles into higher timeframes (15m, 1h, 4h).
Event-driven: triggered when a new 1m candle is inserted.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Tuple
import logging

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Timeframe configurations
TIMEFRAMES = {
    "15m": {"minutes": 15, "label": "15m"},
    "1h": {"minutes": 60, "label": "1h"},
    "4h": {"minutes": 240, "label": "4h"},
}


def get_db_connection(database_url: str):
    """Get database connection."""
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)


def get_bucket_start(timestamp: datetime, interval_minutes: int) -> datetime:
    """Calculate the start of the bucket for a given timestamp."""
    # Ensure we're working with naive datetime (UTC)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.replace(tzinfo=None)
    
    # Round down to the nearest interval
    total_minutes = timestamp.hour * 60 + timestamp.minute
    bucket_minutes = (total_minutes // interval_minutes) * interval_minutes
    bucket_hour = bucket_minutes // 60
    bucket_minute = bucket_minutes % 60
    
    return timestamp.replace(
        hour=bucket_hour,
        minute=bucket_minute,
        second=0,
        microsecond=0
    )


def aggregate_candles(
    database_url: str,
    market_id: str,
    from_interval: str = "1m",
    to_interval: str = "15m",
    limit: int = 100
) -> int:
    """
    Aggregate candles from one interval to another.
    
    Returns the number of new candles created.
    """
    if to_interval not in TIMEFRAMES:
        logger.error(f"Unknown timeframe: {to_interval}")
        return 0
    
    interval_minutes = TIMEFRAMES[to_interval]["minutes"]
    
    conn = get_db_connection(database_url)
    created_count = 0
    
    try:
        with conn.cursor() as cur:
            # Get the latest bucket we have for this interval
            cur.execute("""
                SELECT MAX(timestamp) as latest
                FROM market_candles
                WHERE market_id = %s AND interval = %s
            """, (market_id, to_interval))
            row = cur.fetchone()
            latest_bucket = row["latest"] if row and row["latest"] else None
            
            # Get 1m candles that need to be aggregated
            if latest_bucket:
                # Get candles after the last bucket
                cur.execute("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM market_candles
                    WHERE market_id = %s AND interval = %s
                      AND timestamp > %s
                    ORDER BY timestamp ASC
                    LIMIT %s
                """, (market_id, from_interval, latest_bucket, limit))
            else:
                # No existing buckets, aggregate all available
                cur.execute("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM market_candles
                    WHERE market_id = %s AND interval = %s
                    ORDER BY timestamp ASC
                    LIMIT %s
                """, (market_id, from_interval, limit))
            
            candles = cur.fetchall()
            
            if not candles:
                return 0
            
            # Group candles by bucket
            buckets: Dict[datetime, List] = {}
            for candle in candles:
                ts = candle["timestamp"]
                # Strip timezone for comparison
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                bucket_start = get_bucket_start(ts, interval_minutes)
                if bucket_start not in buckets:
                    buckets[bucket_start] = []
                buckets[bucket_start].append(candle)
            
            # Create aggregated candles for complete buckets only
            now = datetime.utcnow()
            current_bucket = get_bucket_start(now, interval_minutes)
            
            # Also strip tz from latest_bucket if present
            if latest_bucket and latest_bucket.tzinfo is not None:
                latest_bucket = latest_bucket.replace(tzinfo=None)
            
            for bucket_start, bucket_candles in sorted(buckets.items()):
                # Skip the current (incomplete) bucket
                if bucket_start >= current_bucket:
                    continue
                
                # Check if bucket is complete
                expected_candles = interval_minutes
                # For 1m source, we expect interval_minutes candles per bucket
                
                # Aggregate OHLCV
                opens = [Decimal(str(c["open"])) for c in bucket_candles]
                highs = [Decimal(str(c["high"])) for c in bucket_candles]
                lows = [Decimal(str(c["low"])) for c in bucket_candles]
                closes = [Decimal(str(c["close"])) for c in bucket_candles]
                volumes = [Decimal(str(c["volume"])) for c in bucket_candles]
                
                if not closes:
                    continue
                
                agg_open = opens[0]
                agg_high = max(highs)
                agg_low = min(lows)
                agg_close = closes[-1]
                agg_volume = sum(volumes)
                
                # Insert aggregated candle
                cur.execute("""
                    INSERT INTO market_candles 
                        (market_id, interval, timestamp, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (market_id, interval, timestamp) DO UPDATE SET
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """, (
                    market_id, to_interval, bucket_start,
                    agg_open, agg_high, agg_low, agg_close, agg_volume
                ))
                created_count += 1
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"Failed to aggregate candles: {e}")
        conn.rollback()
    finally:
        conn.close()
    
    return created_count


def aggregate_all_timeframes(database_url: str, market_id: str) -> Dict[str, int]:
    """
    Aggregate 1m candles to all higher timeframes.
    
    Returns dict of {timeframe: count} for created candles.
    """
    results = {}
    
    for timeframe in ["15m", "1h", "4h"]:
        count = aggregate_candles(
            database_url, market_id,
            from_interval="1m",
            to_interval=timeframe
        )
        if count > 0:
            logger.info(f"Created {count} {timeframe} candles for market {market_id}")
        results[timeframe] = count
    
    return results


def on_new_1m_candle(database_url: str, market_id: str, candle_time: datetime):
    """
    Called when a new 1m candle is inserted.
    Triggers aggregation if we've crossed a bucket boundary.
    """
    # Check if we've crossed any bucket boundaries
    for timeframe, config in TIMEFRAMES.items():
        interval_minutes = config["minutes"]
        
        # Check if this candle completes a bucket
        bucket_start = get_bucket_start(candle_time, interval_minutes)
        bucket_end = bucket_start + timedelta(minutes=interval_minutes)
        
        # If the next candle would be in a new bucket, aggregate the previous one
        if candle_time.minute % interval_minutes == interval_minutes - 1:
            # This is the last candle in the bucket, trigger aggregation
            aggregate_candles(database_url, market_id, "1m", timeframe, limit=interval_minutes + 10)
