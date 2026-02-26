"""
Relative Strength Index (RSI) indicator.

RSI measures momentum and speed of price movements.
- RSI > 70: Overbought (potential reversal down)
- RSI < 30: Oversold (potential reversal up)
"""
from decimal import Decimal
from typing import List, Optional
import math


def calculate_rsi(
    closes: List[Decimal],
    period: int = 14
) -> Optional[Decimal]:
    """
    Calculate RSI using Wilder's smoothing.
    
    Args:
        closes: List of close prices (oldest first)
        period: RSI period (default 14)
    
    Returns:
        RSI value (0-100) or None if insufficient data
    """
    if len(closes) < period + 1:
        return None
    
    # Calculate price changes
    changes = []
    for i in range(1, len(closes)):
        change = float(closes[i]) - float(closes[i-1])
        changes.append(change)
    
    if len(changes) < period:
        return None
    
    # First average gain/loss
    gains = [c if c > 0 else 0 for c in changes[:period]]
    losses = [-c if c < 0 else 0 for c in changes[:period]]
    
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    # Wilder's smoothing for remaining periods
    for i in range(period, len(changes)):
        change = changes[i]
        gain = change if change > 0 else 0
        loss = -change if change < 0 else 0
        
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
    
    # Calculate RSI
    if avg_loss == 0:
        return Decimal("100")
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return Decimal(str(round(rsi, 2)))


def is_overbought(rsi: Decimal, threshold: Decimal = Decimal("70")) -> bool:
    """Check if RSI indicates overbought conditions."""
    return rsi >= threshold


def is_oversold(rsi: Decimal, threshold: Decimal = Decimal("30")) -> bool:
    """Check if RSI indicates oversold conditions."""
    return rsi <= threshold


def rsi_signal(rsi: Decimal, overbought: Decimal = Decimal("70"), 
               oversold: Decimal = Decimal("30")) -> Optional[str]:
    """
    Generate RSI signal.
    
    Returns:
        'SELL' if overbought, 'BUY' if oversold, None otherwise
    """
    if rsi >= overbought:
        return "SELL"
    if rsi <= oversold:
        return "BUY"
    return None
