"""Data provider base and implementations."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from decimal import Decimal
from dataclasses import dataclass
import requests


@dataclass
class Ticker:
    symbol: str
    price: Decimal
    timestamp: int  # unix ms
    source: str


class DataProvider(ABC):
    """Base class for data providers."""
    
    @abstractmethod
    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """Get current price for a symbol."""
        pass
    
    @abstractmethod
    def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Get OHLCV candles."""
        pass


class BinanceProvider(DataProvider):
    """Binance public API data provider."""
    
    BASE_URL = "https://api.binance.com"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Polypaper/1.0"})
    
    def _convert_symbol(self, symbol: str) -> str:
        """Convert internal symbol to Binance format."""
        # BTC-USD -> BTCUSDT
        return symbol.replace("-", "") + "T"
    
    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """Get current price from Binance."""
        try:
            binance_symbol = self._convert_symbol(symbol)
            resp = self.session.get(
                f"{self.BASE_URL}/api/v3/ticker/price",
                params={"symbol": binance_symbol},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            
            return Ticker(
                symbol=symbol,
                price=Decimal(data["price"]),
                timestamp=int(resp.headers.get("X-Mbx-Used-Weight-Timestamp", 0) or 0),
                source="BINANCE"
            )
        except Exception as e:
            print(f"[Binance] Error fetching {symbol}: {e}")
            return None
    
    def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Get OHLCV candles from Binance."""
        try:
            binance_symbol = self._convert_symbol(symbol)
            resp = self.session.get(
                f"{self.BASE_URL}/api/v3/klines",
                params={"symbol": binance_symbol, "interval": interval, "limit": limit},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            
            return [
                {
                    "timestamp": candle[0],
                    "open": Decimal(candle[1]),
                    "high": Decimal(candle[2]),
                    "low": Decimal(candle[3]),
                    "close": Decimal(candle[4]),
                    "volume": Decimal(candle[5]),
                }
                for candle in data
            ]
        except Exception as e:
            print(f"[Binance] Error fetching OHLCV for {symbol}: {e}")
            return []


class PolymarketProvider(DataProvider):
    """Polymarket Gamma API data provider (public, no auth required)."""
    
    GAMMA_API = "https://gamma-api.polymarket.com"
    CLOB_API = "https://clob.polymarket.com"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Polypaper/1.0"})
    
    def get_active_markets(self, limit: int = 20) -> List[Dict]:
        """Fetch active prediction markets from Polymarket."""
        try:
            resp = self.session.get(
                f"{self.GAMMA_API}/markets",
                params={"limit": limit, "active": "true"},
                timeout=15
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[Polymarket] Error fetching markets: {e}")
            return []
    
    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """Get current price for a Polymarket market."""
        try:
            # symbol should be the condition_id or token_id
            resp = self.session.get(
                f"{self.CLOB_API}/price",
                params={"token_id": symbol},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                return Ticker(
                    symbol=symbol,
                    price=Decimal(data.get("price", "0.5")),
                    timestamp=int(resp.elapsed.total_seconds() * 1000),
                    source="POLYMARKET"
                )
        except Exception as e:
            print(f"[Polymarket] Error fetching {symbol}: {e}")
        return None
    
    def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Polymarket doesn't provide OHLCV, return empty."""
        return []


def get_provider(source: str) -> DataProvider:
    """Get data provider by source name."""
    providers = {
        "BINANCE": BinanceProvider,
        "POLYMARKET": PolymarketProvider,
    }
    
    if source not in providers:
        raise ValueError(f"Unknown data source: {source}")
    
    return providers[source]()
