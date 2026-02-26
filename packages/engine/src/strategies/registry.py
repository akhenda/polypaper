"""Strategy registry."""
from typing import Dict, Type
from .base import Strategy
from .examples.late_entry import LateEntryStrategy


_strategies: Dict[str, Type[Strategy]] = {
    "late-entry-v1": LateEntryStrategy,
}


def get_strategy(strategy_id: str) -> Type[Strategy]:
    """Get strategy class by ID."""
    if strategy_id not in _strategies:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    return _strategies[strategy_id]


def list_strategies() -> Dict[str, Type[Strategy]]:
    """List all available strategies."""
    return _strategies.copy()
