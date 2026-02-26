"""
Bollinger Bands indicator.

Bollinger Bands consist of:
- Middle band: Simple Moving Average (SMA)
- Upper band: SMA + (2 * standard deviation)
- Lower band: SMA - (2 * standard deviation)

Band width indicates volatility:
- Narrow bands = low volatility (potential breakout)
- Wide bands = high volatility
"""
from decimal import Decimal
from typing import List, Optional, Tuple
import math


def calculate_bollinger_bands(
    closes: List[Decimal],
    period: int = 20,
    num_std: float = 2.0
) -> Optional[Tuple[Decimal, Decimal, Decimal, Decimal]]:
    """
    Calculate Bollinger Bands.
    
    Args:
        closes: List of close prices (oldest first)
        period: SMA period (default 20)
        num_std: Number of standard deviations (default 2.0)
    
    Returns:
        Tuple of (upper, middle, lower, width) or None if insufficient data
    """
    if len(closes) < period:
        return None
    
    # Get the most recent 'period' closes
    recent_closes = [float(c) for c in closes[-period:]]
    
    # Calculate SMA (middle band)
    sma = sum(recent_closes) / period
    
    # Calculate standard deviation
    variance = sum((c - sma) ** 2 for c in recent_closes) / period
    std_dev = math.sqrt(variance)
    
    # Calculate bands
    upper = sma + (num_std * std_dev)
    lower = sma - (num_std * std_dev)
    
    # Calculate bandwidth as percentage of SMA
    bandwidth = ((upper - lower) / sma) * 100 if sma > 0 else 0
    
    return (
        Decimal(str(round(upper, 8))),
        Decimal(str(round(sma, 8))),
        Decimal(str(round(lower, 8))),
        Decimal(str(round(bandwidth, 4)))
    )


def get_band_position(price: Decimal, upper: Decimal, middle: Decimal, 
                      lower: Decimal) -> str:
    """
    Get position within Bollinger Bands.
    
    Returns: 'UPPER', 'MIDDLE', 'LOWER', 'ABOVE', or 'BELOW'
    """
    if price > upper:
        return "ABOVE"
    elif price < lower:
        return "BELOW"
    elif price > middle:
        return "UPPER"
    else:
        return "LOWER"


def is_squeeze(bandwidth: Decimal, threshold: Decimal = Decimal("4.0")) -> bool:
    """
    Check if bands are in a squeeze (low volatility, potential breakout).
    
    Args:
        bandwidth: Current bandwidth as % of middle
        threshold: Squeeze threshold (default 4%)
    
    Returns:
        True if in squeeze
    """
    return bandwidth < threshold


def is_expansion(bandwidth: Decimal, threshold: Decimal = Decimal("8.0")) -> bool:
    """
    Check if bands are expanding (high volatility).
    
    Args:
        bandwidth: Current bandwidth as % of middle
        threshold: Expansion threshold (default 8%)
    
    Returns:
        True if expanding
    """
    return bandwidth > threshold


def mean_reversion_signal(price: Decimal, upper: Decimal, middle: Decimal,
                          lower: Decimal, bandwidth_min: Decimal = Decimal("5.0")) -> Optional[str]:
    """
    Generate mean reversion signal.
    
    Only signals when bandwidth is wide enough (avoid low-vol chop).
    
    Returns:
        'BUY' if price at lower band, 'SELL' if at upper band, None otherwise
    """
    if bandwidth_min > 0:
        # Calculate bandwidth
        bandwidth = ((upper - lower) / middle) * 100 if middle > 0 else 0
        if bandwidth < float(bandwidth_min):
            return None  # Not enough volatility for mean reversion
    
    # Price near lower band - buy signal (expect reversion to mean)
    lower_threshold = lower + (middle - lower) * Decimal("0.2")  # Within 20% of lower
    if price <= lower_threshold:
        return "BUY"
    
    # Price near upper band - sell signal (expect reversion to mean)
    upper_threshold = upper - (upper - middle) * Decimal("0.2")  # Within 20% of upper
    if price >= upper_threshold:
        return "SELL"
    
    return None
