# Strategies module
from .base import Strategy, StrategyMetadata, MarketData, Position, Signal, SignalType
from .examples import LateEntryStrategy, TrendFollowingStrategy, MeanReversionStrategy

# Strategy registry for dynamic loading
STRATEGY_REGISTRY = {
    "late-entry-v1": LateEntryStrategy,
    "trend-following-v1": TrendFollowingStrategy,
    "mean-reversion-v1": MeanReversionStrategy,
}

__all__ = [
    "Strategy", "StrategyMetadata", "MarketData", "Position", "Signal", "SignalType",
    "LateEntryStrategy", "TrendFollowingStrategy", "MeanReversionStrategy",
    "STRATEGY_REGISTRY"
]
