"""
Polymarket Gamma API Client

Read-only client for market discovery from Polymarket Gamma API.
https://gamma-api.polymarket.com

Used to discover active prediction markets and their metadata.
"""
import os
import time
import json
import logging
import requests
from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)

GAMMA_API_URL = "https://gamma-api.polymarket.com"
REQUEST_TIMEOUT = 10
RATE_LIMIT_DELAY = 0.5  # Conservative delay between requests
last_request_time = 0


def _make_request(endpoint: str, params: Dict = None) -> Optional[Dict]:
    """Make a rate-limited request to Gamma API."""
    global last_request_time
    
    # Rate limiting
    elapsed = time.time() - last_request_time
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)
    
    url = f"{GAMMA_API_URL}{endpoint}"
    
    max_retries = 3
    base_delay = 1
    
    for attempt in range(max_retries):
        try:
            last_request_time = time.time()
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )
            
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"Gamma API rate limited, waiting {retry_after}s")
                time.sleep(retry_after)
                continue
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.warning(f"Gamma API timeout (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Gamma API error: {e}")
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    
    return None


def fetch_events(
    active: bool = True,
    closed: bool = False,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Fetch events from Gamma API.
    
    Args:
        active: Only active events
        closed: Include closed events
        limit: Number of events per page
        offset: Pagination offset
    
    Returns:
        List of event objects
    """
    params = {
        "active": str(active).lower(),
        "closed": str(closed).lower(),
        "limit": limit,
        "offset": offset
    }
    
    data = _make_request("/events", params)
    return data if isinstance(data, list) else []


def fetch_event(event_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single event by ID."""
    return _make_request(f"/events/{event_id}")


def fetch_markets(event_id: str = None, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch markets from Gamma API.
    
    Args:
        event_id: Filter by event ID
        limit: Number of markets
    
    Returns:
        List of market objects
    """
    params = {"limit": limit}
    if event_id:
        params["event_id"] = event_id
    
    data = _make_request("/markets", params)
    return data if isinstance(data, list) else []


def extract_market_info(market: Dict) -> Dict[str, Any]:
    """
    Extract useful market info from Gamma API market object.
    
    Returns a dict with:
    - market_id: Polymarket market ID
    - question: Market question
    - slug: Market slug
    - outcomes: List of outcome names
    - outcome_prices: Current prices for each outcome
    - token_ids: CLOB token IDs for each outcome
    - active: Whether market is active
    """
    # Get token IDs - handle different field names and formats
    token_ids = market.get("clobTokenIds") or market.get("clob_token_ids") or []
    
    # Token IDs may be a JSON string or already a list
    if isinstance(token_ids, str):
        try:
            token_ids = json.loads(token_ids)
        except (json.JSONDecodeError, ValueError):
            token_ids = []
    
    # If still empty, check tokens array
    if not token_ids and isinstance(market.get("tokens"), list):
        token_ids = [t.get("token_id") or t.get("clobTokenId") for t in market["tokens"] if t]
    
    # Clean up token IDs
    token_ids = [str(tid) for tid in token_ids if tid]
    
    return {
        "market_id": str(market.get("id") or market.get("conditionId", "")),
        "question": market.get("question"),
        "slug": market.get("slug"),
        "outcomes": market.get("outcomes", []),
        "outcome_prices": market.get("outcomePrices") or market.get("outcome_prices", []),
        "token_ids": token_ids,
        "active": market.get("active", True),
        "closed": market.get("resolved") or market.get("closed", False),
        "end_date": market.get("endDateIso") or market.get("end_date_iso"),
        "volume": market.get("volume") or market.get("volumeNum"),
        "event_id": market.get("events", [{}])[0].get("id") if market.get("events") else market.get("event_id"),
        "event_slug": market.get("events", [{}])[0].get("slug") if market.get("events") else market.get("event_slug"),
        "image": market.get("image"),
        "description": market.get("description"),
    }


def discover_active_markets(max_markets: int = 500) -> List[Dict[str, Any]]:
    """
    Discover all active markets by fetching directly from /markets endpoint.
    
    Args:
        max_markets: Maximum number of markets to fetch
    
    Returns:
        List of extracted market info dicts
    """
    all_markets = []
    offset = 0
    limit = 100
    
    while len(all_markets) < max_markets:
        logger.info(f"Fetching markets offset={offset}, total={len(all_markets)}")
        
        # Use /markets endpoint which has clobTokenIds
        params = {
            "limit": limit,
            "offset": offset,
            "active": "true",
            "closed": "false"
        }
        
        data = _make_request("/markets", params)
        
        if not data or not isinstance(data, list):
            break
        
        for market in data:
            market_info = extract_market_info(market)
            if market_info["market_id"] and market_info.get("token_ids"):
                all_markets.append(market_info)
        
        offset += limit
        
        if len(data) < limit:
            break
        
        if len(all_markets) >= max_markets:
            break
    
    logger.info(f"Discovered {len(all_markets)} active markets with token IDs")
    return all_markets[:max_markets]


if __name__ == "__main__":
    # Test the client
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Polymarket Gamma API...")
    markets = discover_active_markets(max_events=50)
    
    for m in markets[:5]:
        print(f"\n{m['question'][:80]}...")
        print(f"  Slug: {m['slug']}")
        print(f"  Outcomes: {m['outcomes']}")
        print(f"  Token IDs: {m['token_ids'][:2]}...")
