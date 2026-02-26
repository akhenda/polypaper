# Example strategies
from .late_entry import LateEntryStrategy
from .trend_following import TrendFollowingStrategy
from .mean_reversion import MeanReversionStrategy

__all__ = ["LateEntryStrategy", "TrendFollowingStrategy", "MeanReversionStrategy"]

# Strategy registry
STRATEGY_REGISTRY = {
    "late-entry-v1": LateEntryStrategy,
    "trend-following-v1": TrendFollowingStrategy,
    "mean-reversion-v1": MeanReversionStrategy,
}
