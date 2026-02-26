"""Strategy base classes and interfaces."""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"


@dataclass
class MarketData:
    symbol: str
    timestamp: int  # unix ms
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class Position:
    symbol: str
    side: str
    quantity: Decimal
    avg_entry_price: Decimal


@dataclass
class Signal:
    symbol: str
    signal_type: SignalType
    quantity: Optional[Decimal] = None
    price: Optional[Decimal] = None
    confidence: float = 1.0
    reason: str = ""


@dataclass
class StrategyMetadata:
    id: str
    name: str
    description: str
    version: str
    supported_markets: List[str]
    parameters: Dict[str, Any]


class Strategy(ABC):
    """Base class for all trading strategies."""
    
    @classmethod
    @abstractmethod
    def metadata(cls) -> StrategyMetadata:
        """Return strategy metadata and parameter schema."""
        pass
    
    @abstractmethod
    def __init__(self, parameters: Dict[str, Any]):
        """Initialize strategy with user-provided parameters."""
        pass
    
    @abstractmethod
    def on_data(self, data: MarketData, positions: List[Position]) -> Optional[Signal]:
        """Called for each new data point. Return Signal or None."""
        pass
    
    def on_fill(self, order_id: str, filled_qty: Decimal, fill_price: Decimal):
        """Optional: Called when an order is filled."""
        pass
    
    def on_position_change(self, position: Position):
        """Optional: Called when a position is updated."""
        pass
    
    def get_required_history(self) -> int:
        """Return number of candles needed before strategy can signal."""
        return 1
