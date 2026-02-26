"""
Polymarket CLOB API Client

Read-only client for fetching orderbook and prices from Polymarket CLOB.
https://clob.polymarket.com

Used to get current mid prices for prediction market outcomes.
"""
import os
import time
import logging
import json
import requests
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CLOB_API_URL = "https://clob.polymarket.com"
REQUEST_TIMEOUT = 10
RATE_LIMIT_DELAY = 0.3  # Conservative delay
last_request_time = 0

# Cache settings (simple in-memory cache)
_price_cache: Dict[str, Tuple[float, Decimal]] = {}  # token_id -> (timestamp, mid_price)
_orderbook_cache: Dict[str, Tuple[float, Dict]] = {}  # token_id -> (timestamp, orderbook)
CACHE_TTL_SECONDS = 30  # Cache prices for 30 seconds


def _make_request(endpoint: str, params: Dict = None) -> Optional[Dict]:
    """Make a rate-limited request to CLOB API."""
    global last_request_time
    
    # Rate limiting
    elapsed = time.time() - last_request_time
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)
    
    url = f"{CLOB_API_URL}{endpoint}"
    
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
                retry_after = int(response.headers.get("Retry-After", 30))
                logger.warning(f"CLOB API rate limited, waiting {retry_after}s")
                time.sleep(retry_after)
                continue
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.warning(f"CLOB API timeout (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
                
        except requests.exceptions.RequestException as e:
            logger.error(f"CLOB API error: {e}")
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    
    return None


def fetch_orderbook(token_id: str, use_cache: bool = True) -> Optional[Dict]:
    """
    Fetch the orderbook for a token.
    
    Args:
        token_id: The CLOB token ID
        use_cache: Whether to use cached data
    
    Returns:
        Orderbook dict with 'bids' and 'asks' lists
    """
    now = time.time()
    
    # Check cache
    if use_cache and token_id in _orderbook_cache:
        cache_time, cached_book = _orderbook_cache[token_id]
        if now - cache_time < CACHE_TTL_SECONDS:
            return cached_book
    
    # Fetch from API
    data = _make_request("/book", {"token_id": token_id})
    
    if data:
        _orderbook_cache[token_id] = (now, data)
        return data
    
    return None


def calculate_mid_price(orderbook: Dict) -> Optional[Decimal]:
    """
    Calculate mid price from orderbook.
    
    Mid = (best_bid + best_ask) / 2
    Falls back to best available side if one is missing.
    
    Args:
        orderbook: Dict with 'bids' and 'asks' lists
    
    Returns:
        Mid price as Decimal (0-1 scale) or None
    """
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])
    
    best_bid = None
    best_ask = None
    
    if bids:
        # Bids are sorted by price descending, first is best
        try:
            best_bid = Decimal(str(bids[0].get("price", 0)))
        except (KeyError, ValueError):
            pass
    
    if asks:
        # Asks are sorted by price ascending, first is best
        try:
            best_ask = Decimal(str(asks[0].get("price", 0)))
        except (KeyError, ValueError):
            pass
    
    if best_bid is not None and best_ask is not None:
        # Normal case: both sides available
        mid = (best_bid + best_ask) / 2
    elif best_bid is not None:
        # Only bids available
        mid = best_bid
    elif best_ask is not None:
        # Only asks available
        mid = best_ask
    else:
        # No liquidity
        return None
    
    # Ensure price is in valid range
    mid = max(Decimal("0.01"), min(Decimal("0.99"), mid))
    
    return mid


def get_mid_price(token_id: str, use_cache: bool = True) -> Optional[Decimal]:
    """
    Get the current mid price for a token.
    
    Args:
        token_id: The CLOB token ID
        use_cache: Whether to use cached data
    
    Returns:
        Mid price as Decimal (0-1 scale) or None
    """
    now = time.time()
    
    # Check cache
    if use_cache and token_id in _price_cache:
        cache_time, cached_price = _price_cache[token_id]
        if now - cache_time < CACHE_TTL_SECONDS:
            return cached_price
    
    # Fetch orderbook and calculate mid
    orderbook = fetch_orderbook(token_id, use_cache=False)
    
    if orderbook:
        mid = calculate_mid_price(orderbook)
        if mid is not None:
            _price_cache[token_id] = (now, mid)
            return mid
    
    return None


def get_spread(orderbook: Dict) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
    """
    Get the bid-ask spread.
    
    Returns:
        Tuple of (spread, bid, ask) or None if insufficient liquidity
    """
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])
    
    if not bids or not asks:
        return None
    
    try:
        best_bid = Decimal(str(bids[0].get("price", 0)))
        best_ask = Decimal(str(asks[0].get("price", 0)))
        spread = best_ask - best_bid
        return (spread, best_bid, best_ask)
    except (KeyError, ValueError):
        return None


def fetch_mid_prices_batch(token_ids: List[str]) -> Dict[str, Optional[Decimal]]:
    """
    Fetch mid prices for multiple tokens.
    
    Args:
        token_ids: List of token IDs
    
    Returns:
        Dict mapping token_id -> mid_price
    """
    results = {}
    
    for token_id in token_ids:
        price = get_mid_price(token_id)
        results[token_id] = price
        # Small delay to avoid rate limiting
        time.sleep(0.1)
    
    return results


if __name__ == "__main__":
    # Test the client
    logging.basicConfig(level=logging.INFO)
    
    # Known test token IDs (will need to be updated with real ones)
    test_tokens = [
        "69236623772367432316263934436371082691718440313730055357097950845439144812907",  # Example
    ]
    
    print("Testing Polymarket CLOB API...")
    
    for token_id in test_tokens[:1]:
        print(f"\nFetching orderbook for token: {token_id[:20]}...")
        
        orderbook = fetch_orderbook(token_id, use_cache=False)
        
        if orderbook:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            print(f"  Bids: {len(bids)}, Asks: {len(asks)}")
            
            if bids:
                print(f"  Best bid: {bids[0].get('price')}")
            if asks:
                print(f"  Best ask: {asks[0].get('price')}")
            
            mid = calculate_mid_price(orderbook)
            spread_info = get_spread(orderbook)
            
            if mid:
                print(f"  Mid price: {mid}")
            if spread_info:
                spread, bid, ask = spread_info
                print(f"  Spread: {spread} ({float(spread)*100:.2f}%)")
        else:
            print("  Failed to fetch orderbook")
