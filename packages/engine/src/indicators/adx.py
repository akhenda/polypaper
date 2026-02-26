"""
Average Directional Index (ADX) indicator.

ADX measures trend strength regardless of direction.
- ADX > 25: Strong trend
- ADX < 20: Weak/no trend

Uses +DI and -DI to determine trend direction.
"""
from decimal import Decimal
from typing import List, Tuple, Optional
import math


def calculate_adx(
    highs: List[Decimal],
    lows: List[Decimal],
    closes: List[Decimal],
    period: int = 14
) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
    """
    Calculate ADX, +DI, and -DI.
    
    Args:
        highs: List of high prices (oldest first)
        lows: List of low prices
        closes: List of close prices
        period: ADX period (default 14)
    
    Returns:
        Tuple of (adx, plus_di, minus_di) or None if insufficient data
    """
    if len(highs) < period * 2:
        return None
    
    n = len(highs)
    
    # Calculate True Range and Directional Movement
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []
    
    for i in range(1, n):
        high = float(highs[i])
        low = float(lows[i])
        close_prev = float(closes[i-1])
        high_prev = float(highs[i-1])
        low_prev = float(lows[i-1])
        
        # True Range
        tr = max(
            high - low,
            abs(high - close_prev),
            abs(low - close_prev)
        )
        tr_list.append(tr)
        
        # Directional Movement
        up_move = high - high_prev
        down_move = low_prev - low
        
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0
        
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    
    if len(tr_list) < period:
        return None
    
    # Smooth the values using Wilder's smoothing
    def smooth(values: List[float], period: int) -> List[float]:
        smoothed = [sum(values[:period])]
        for i in range(period, len(values)):
            smoothed.append(smoothed[-1] - smoothed[-1] / period + values[i])
        return smoothed
    
    smoothed_tr = smooth(tr_list, period)
    smoothed_plus_dm = smooth(plus_dm_list, period)
    smoothed_minus_dm = smooth(minus_dm_list, period)
    
    # Calculate DI
    plus_di_vals = []
    minus_di_vals = []
    
    for i in range(len(smoothed_tr)):
        if smoothed_tr[i] > 0:
            plus_di_vals.append((smoothed_plus_dm[i] / smoothed_tr[i]) * 100)
            minus_di_vals.append((smoothed_minus_dm[i] / smoothed_tr[i]) * 100)
        else:
            plus_di_vals.append(0)
            minus_di_vals.append(0)
    
    # Calculate DX
    dx_list = []
    for i in range(len(plus_di_vals)):
        di_sum = plus_di_vals[i] + minus_di_vals[i]
        if di_sum > 0:
            dx = abs(plus_di_vals[i] - minus_di_vals[i]) / di_sum * 100
        else:
            dx = 0
        dx_list.append(dx)
    
    if len(dx_list) < period:
        return None
    
    # Calculate ADX (smoothed DX)
    adx_vals = smooth(dx_list, period)
    
    # Return latest values
    latest_adx = Decimal(str(round(adx_vals[-1], 2)))
    latest_plus_di = Decimal(str(round(plus_di_vals[-1], 2)))
    latest_minus_di = Decimal(str(round(minus_di_vals[-1], 2)))
    
    return (latest_adx, latest_plus_di, latest_minus_di)


def get_trend_direction(adx: Decimal, plus_di: Decimal, minus_di: Decimal, 
                        threshold: Decimal = Decimal("25")) -> str:
    """
    Determine trend direction based on ADX and DI.
    
    Returns: 'BULLISH', 'BEARISH', or 'NEUTRAL'
    """
    if adx < threshold:
        return "NEUTRAL"
    
    if plus_di > minus_di:
        return "BULLISH"
    elif minus_di > plus_di:
        return "BEARISH"
    else:
        return "NEUTRAL"


def is_trending(adx: Decimal, threshold: Decimal = Decimal("25")) -> bool:
    """Check if market is trending (ADX above threshold)."""
    return adx >= threshold
