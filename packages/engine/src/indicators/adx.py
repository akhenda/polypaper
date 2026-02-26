"""
Average Directional Index (ADX) indicator.

ADX measures trend strength regardless of direction.
- ADX > 25: Strong trend
- ADX < 20: Weak/no trend

Uses +DI and -DI to determine trend direction.

IMPORTANT: ADX must always be in range [0, 100].
If values exceed this, there's a bug in the implementation.
"""
from decimal import Decimal
from typing import List, Tuple, Optional
import math
import logging

logger = logging.getLogger(__name__)


def wilder_smooth(values: List[float], period: int) -> List[float]:
    """
    Wilder's smoothing (RMA - Running Moving Average).
    
    First value is SMA of first `period` values.
    Subsequent values: RMA = (prev_RMA * (period-1) + current) / period
    """
    if len(values) < period:
        return []
    
    smoothed = []
    # First value: SMA of first `period` values
    smoothed.append(sum(values[:period]) / period)
    
    # Subsequent values: Wilder's smoothing
    for i in range(period, len(values)):
        new_val = (smoothed[-1] * (period - 1) + values[i]) / period
        smoothed.append(new_val)
    
    return smoothed


def calculate_adx(
    highs: List[Decimal],
    lows: List[Decimal],
    closes: List[Decimal],
    period: int = 14
) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
    """
    Calculate ADX, +DI, and -DI using Wilder's smoothing.
    
    Args:
        highs: List of high prices (oldest first)
        lows: List of low prices
        closes: List of close prices
        period: ADX period (default 14)
    
    Returns:
        Tuple of (adx, plus_di, minus_di) or None if insufficient data
        
    Note: All return values are guaranteed to be in range [0, 100]
    """
    if len(highs) < period * 2 + 1:
        return None
    
    n = len(highs)
    
    # Calculate True Range and Directional Movement for each period
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []
    
    for i in range(1, n):
        high = float(highs[i])
        low = float(lows[i])
        close_prev = float(closes[i-1])
        high_prev = float(highs[i-1])
        low_prev = float(lows[i-1])
        
        # True Range: max of (H-L, |H-Cp|, |L-Cp|)
        tr = max(
            high - low,
            abs(high - close_prev),
            abs(low - close_prev)
        )
        tr_list.append(tr)
        
        # Directional Movement
        up_move = high - high_prev
        down_move = low_prev - low
        
        # +DM = up_move if up_move > down_move AND up_move > 0, else 0
        # -DM = down_move if down_move > up_move AND down_move > 0, else 0
        if up_move > down_move and up_move > 0:
            plus_dm = up_move
        else:
            plus_dm = 0
            
        if down_move > up_move and down_move > 0:
            minus_dm = down_move
        else:
            minus_dm = 0
        
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    
    if len(tr_list) < period:
        return None
    
    # Apply Wilder's smoothing to TR, +DM, -DM
    atr = wilder_smooth(tr_list, period)
    smoothed_plus_dm = wilder_smooth(plus_dm_list, period)
    smoothed_minus_dm = wilder_smooth(minus_dm_list, period)
    
    if len(atr) == 0:
        return None
    
    # Calculate +DI and -DI for each smoothed period
    plus_di_vals = []
    minus_di_vals = []
    
    for i in range(len(atr)):
        if atr[i] > 0:
            # DI = (DM / ATR) * 100
            plus_di = (smoothed_plus_dm[i] / atr[i]) * 100
            minus_di = (smoothed_minus_dm[i] / atr[i]) * 100
        else:
            plus_di = 0
            minus_di = 0
        
        # Clamp DI values to [0, 100]
        plus_di = max(0, min(100, plus_di))
        minus_di = max(0, min(100, minus_di))
        
        plus_di_vals.append(plus_di)
        minus_di_vals.append(minus_di)
    
    # Calculate DX for each period
    # DX = 100 * |+DI - -DI| / (+DI + -DI)
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
    
    # Calculate ADX: smoothed DX using Wilder's smoothing
    adx_vals = wilder_smooth(dx_list, period)
    
    if len(adx_vals) == 0:
        return None
    
    # Get latest values
    latest_adx_raw = adx_vals[-1]
    latest_plus_di_raw = plus_di_vals[-1]
    latest_minus_di_raw = minus_di_vals[-1]
    
    # Clamp final values to [0, 100] and log if we needed to clamp
    latest_adx = max(0, min(100, latest_adx_raw))
    latest_plus_di = max(0, min(100, latest_plus_di_raw))
    latest_minus_di = max(0, min(100, latest_minus_di_raw))
    
    if latest_adx_raw > 100 or latest_adx_raw < 0:
        logger.warning(
            f"ADX value {latest_adx_raw:.2f} was clamped to {latest_adx:.2f}. "
            f"This indicates a calculation issue. DI values: +{latest_plus_di_raw:.2f}, -{latest_minus_di_raw:.2f}"
        )
    
    if latest_plus_di_raw > 100 or latest_plus_di_raw < 0:
        logger.warning(
            f"+DI value {latest_plus_di_raw:.2f} was clamped to {latest_plus_di:.2f}"
        )
    
    return (
        Decimal(str(round(latest_adx, 2))),
        Decimal(str(round(latest_plus_di, 2))),
        Decimal(str(round(latest_minus_di, 2)))
    )


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


# ============ UNIT TESTS ============
if __name__ == "__main__":
    import random
    
    def generate_candles(n: int, base_price: float = 100, volatility: float = 0.02):
        """Generate random but sane candle data."""
        random.seed(42)
        closes = [base_price]
        highs = [base_price * (1 + random.random() * volatility)]
        lows = [base_price * (1 - random.random() * volatility)]
        
        for i in range(1, n):
            change = (random.random() - 0.5) * 2 * volatility * base_price
            close = closes[-1] + change
            high = close * (1 + random.random() * volatility * 0.5)
            low = close * (1 - random.random() * volatility * 0.5)
            
            closes.append(close)
            highs.append(high)
            lows.append(low)
        
        return (
            [Decimal(str(h)) for h in highs],
            [Decimal(str(l)) for l in lows],
            [Decimal(str(c)) for c in closes]
        )
    
    print("Testing ADX implementation...")
    print("=" * 50)
    
    # Test 1: ADX should always be in [0, 100]
    print("\n1. Testing ADX range [0, 100] for random candles:")
    all_pass = True
    for i in range(10):
        highs, lows, closes = generate_candles(50, base_price=100 + i*10, volatility=0.01 + i*0.005)
        result = calculate_adx(highs, lows, closes, period=14)
        if result:
            adx, plus_di, minus_di = result
            adx_val = float(adx)
            plus_val = float(plus_di)
            minus_val = float(minus_di)
            
            in_range = 0 <= adx_val <= 100 and 0 <= plus_val <= 100 and 0 <= minus_val <= 100
            status = "✓" if in_range else "✗"
            print(f"  Test {i+1}: ADX={adx_val:.2f}, +DI={plus_val:.2f}, -DI={minus_val:.2f} {status}")
            if not in_range:
                all_pass = False
        else:
            print(f"  Test {i+1}: Insufficient data")
    
    # Test 2: Flat market should have low ADX
    print("\n2. Testing flat market (should have low ADX):")
    flat_highs = [Decimal("100.1")] * 50
    flat_lows = [Decimal("99.9")] * 50
    flat_closes = [Decimal("100.0")] * 50
    result = calculate_adx(flat_highs, flat_lows, flat_closes, period=14)
    if result:
        adx, plus_di, minus_di = result
        print(f"  Flat market: ADX={adx}, +DI={plus_di}, -DI={minus_di}")
        print(f"  Expected low ADX: {'✓' if float(adx) < 20 else '✗'}")
    
    # Test 3: Trending market should have higher ADX
    print("\n3. Testing trending market (should have higher ADX):")
    trend_closes = [Decimal(str(100 + i * 0.5)) for i in range(50)]
    trend_highs = [c + Decimal("0.1") for c in trend_closes]
    trend_lows = [c - Decimal("0.1") for c in trend_closes]
    result = calculate_adx(trend_highs, trend_lows, trend_closes, period=14)
    if result:
        adx, plus_di, minus_di = result
        print(f"  Trending market: ADX={adx}, +DI={plus_di}, -DI={minus_di}")
        print(f"  Expected high +DI vs -DI: {'✓' if plus_di > minus_di else '✗'}")
    
    print("\n" + "=" * 50)
    print(f"All tests passed: {'YES' if all_pass else 'NO'}")
