"""
Polymarket Data Provider

Ingests active markets from Polymarket using public Gamma API.
Read-only - no authenticated trading.
"""
import os
import time
import logging
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

# Gamma API endpoints (public, no auth required)
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
MARKETS_ENDPOINT = f"{GAMMA_API_BASE}/markets"
EVENTS_ENDPOINT = f"{GAMMA_API_BASE}/events"

# Rate limiting
REQUEST_DELAY = 0.5  # Conservative delay between requests
last_request_time = 0


def _rate_limit():
    """Enforce rate limiting."""
    global last_request_time
    elapsed = time.time() - last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    last_request_time = time.time()


def fetch_markets(
    limit: int = 100,
    active_only: bool = True,
    tag: str = None
) -> List[Dict[str, Any]]:
    """
    Fetch markets from Polymarket Gamma API.
    
    Args:
        limit: Maximum number of markets to fetch
        active_only: Only return active markets
        tag: Filter by tag (e.g., "Politics", "Crypto", "Sports")
    
    Returns:
        List of market dicts
    """
    _rate_limit()
    
    params = {
        "limit": limit,
        "closed": "false" if active_only else None,
    }
    
    if tag:
        params["tag"] = tag
    
    # Remove None values
    params = {k: v for k, v in params.items() if v is not None}
    
    try:
        resp = requests.get(MARKETS_ENDPOINT, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Polymarket markets: {e}")
        return []


def fetch_events(limit: int = 50, active_only: bool = True) -> List[Dict[str, Any]]:
    """
    Fetch events from Polymarket Gamma API.
    
    Events contain multiple related markets.
    
    Args:
        limit: Maximum number of events to fetch
        active_only: Only return active events
    
    Returns:
        List of event dicts
    """
    _rate_limit()
    
    params = {
        "limit": limit,
        "closed": "false" if active_only else None,
    }
    
    params = {k: v for k, v in params.items() if v is not None}
    
    try:
        resp = requests.get(EVENTS_ENDPOINT, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Polymarket events: {e}")
        return []


def parse_polymarket_market(market: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a Polymarket market into our format.
    
    Returns:
        Dict with keys: symbol, name, type, source, tick_size, min_quantity, metadata
    """
    # Create symbol from condition ID or slug
    condition_id = market.get("conditionId", "")
    slug = market.get("market_slug", market.get("slug", ""))
    
    # Use slug as symbol, sanitized
    symbol = f"POLY-{slug[:30].upper().replace('-', '_')}" if slug else f"POLY-{condition_id[:8]}"
    
    # Get question/description
    question = market.get("question", market.get("name", "Unknown"))
    
    # Get prices
    yes_price = Decimal(str(market.get("outcomePrices", ["0.5", "0.5"])[0])) / 100
    no_price = Decimal(str(market.get("outcomePrices", ["0.5", "0.5"])[1] if len(market.get("outcomePrices", [])) > 1 else 0.5)) / 100
    
    # Metadata
    metadata = {
        "condition_id": condition_id,
        "question": question,
        "end_date": market.get("endDate"),
        "category": market.get("tags", []),
        "yes_price": str(yes_price),
        "no_price": str(no_price),
        "volume": market.get("volume", "0"),
        "liquidity": market.get("liquidity", "0"),
    }
    
    return {
        "symbol": symbol,
        "name": question[:255],
        "type": "PREDICTION",
        "source": "POLYMARKET",
        "tick_size": "0.01",
        "min_quantity": "1",
        "metadata": metadata,
    }


def ingest_polymarket_markets(db_connection, limit: int = 50) -> int:
    """
    Fetch and store Polymarket markets in the database.
    
    Args:
        db_connection: Database connection
        limit: Maximum number of markets to ingest
    
    Returns:
        Number of markets inserted/updated
    """
    markets = fetch_markets(limit=limit, active_only=True)
    
    if not markets:
        logger.warning("No Polymarket markets fetched")
        return 0
    
    inserted = 0
    
    with db_connection.cursor() as cur:
        for market in markets:
            try:
                parsed = parse_polymarket_market(market)
                
                cur.execute("""
                    INSERT INTO markets (symbol, type, source, name, tick_size, min_quantity, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                """, (
                    parsed["symbol"],
                    parsed["type"],
                    parsed["source"],
                    parsed["name"],
                    parsed["tick_size"],
                    parsed["min_quantity"],
                    json.dumps(parsed["metadata"])
                ))
                inserted += 1
                
            except Exception as e:
                logger.error(f"Failed to insert market {market.get('conditionId', 'unknown')}: {e}")
    
    db_connection.commit()
    logger.info(f"Ingested {inserted} Polymarket markets")
    return inserted


# Import json for metadata serialization
import json
