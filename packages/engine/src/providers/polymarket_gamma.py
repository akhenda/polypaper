"""
Polymarket Gamma API Client

Read-only client for market discovery from Polymarket Gamma API.
https://gamma-api.polymarket.com

Used to discover active prediction markets and their metadata.
"""
import os
import time
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
    return {
        "market_id": market.get("id") or market.get("condition_id"),
        "question": market.get("question"),
        "slug": market.get("market_slug") or market.get("slug"),
        "outcomes": market.get("outcomes", []),
        "outcome_prices": market.get("outcome_prices", []),
        "token_ids": market.get("clob_token_ids", market.get("tokens", [])),
        "active": market.get("active", True),
        "closed": market.get("resolved", False),
        "end_date": market.get("end_date_iso"),
        "volume": market.get("volume"),
        "event_id": market.get("event_id") or market.get("condition_id"),
        "event_slug": market.get("event_slug"),
        "image": market.get("image"),
        "description": market.get("description"),
    }


def discover_active_markets(max_events: int = 200) -> List[Dict[str, Any]]:
    """
    Discover all active markets by paginating through events.
    
    Args:
        max_events: Maximum number of events to scan
    
    Returns:
        List of extracted market info dicts
    """
    all_markets = []
    offset = 0
    limit = 100
    
    while offset < max_events:
        logger.info(f"Fetching events offset={offset}")
        events = fetch_events(active=True, closed=False, limit=limit, offset=offset)
        
        if not events:
            break
        
        for event in events:
            # Extract markets from event
            event_markets = event.get("markets", [])
            
            if not event_markets:
                # Single market event
                market_info = extract_market_info(event)
                if market_info["market_id"]:
                    all_markets.append(market_info)
            else:
                # Multiple markets per event
                for market in event_markets:
                    market["event_slug"] = event.get("slug")
                    market["event_id"] = event.get("id")
                    market_info = extract_market_info(market)
                    if market_info["market_id"]:
                        all_markets.append(market_info)
        
        offset += limit
        
        if len(events) < limit:
            break
    
    logger.info(f"Discovered {len(all_markets)} active markets")
    return all_markets


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
