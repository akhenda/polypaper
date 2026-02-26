"""Trend Following Strategy - follows established trends with ADX filter."""
from decimal import Decimal
from typing import Dict, Any, List, Optional
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import Strategy, StrategyMetadata, MarketData, Position, Signal, SignalType
from indicators.adx import calculate_adx, get_trend_direction, is_trending


class TrendFollowingStrategy(Strategy):
    """
    Trend Following Strategy
    
    - Uses ADX to confirm trend strength (requires ADX > threshold)
    - Enters in direction of trend when price breaks recent high/low
    - Position cap with circuit breaker
    - Trailing stop for exits
    """
    
    @classmethod
    def metadata(cls) -> StrategyMetadata:
        return StrategyMetadata(
            id="trend-following-v1",
            name="Trend Following",
            description="Follows established trends with ADX confirmation and trailing stops",
            version="1.0.0",
            supported_markets=["CRYPTO"],
            parameters={
                "positionCapUsd": {"type": "number", "default": 20, "description": "Maximum position size in USD"},
                "adxThreshold": {"type": "number", "default": 25, "description": "Minimum ADX to confirm trend"},
                "lookbackPeriod": {"type": "number", "default": 20, "description": "Lookback for high/low"},
                "trailingStopPercent": {"type": "number", "default": 2.0, "description": "Trailing stop percentage"},
                "maxConsecutiveLosses": {"type": "number", "default": 3, "description": "Circuit breaker threshold"},
                "cooldownHours": {"type": "number", "default": 24, "description": "Cooldown period"},
                "intervalMinutes": {"type": "number", "default": 240, "description": "Strategy interval (4h)"},
            }
        )
    
    def __init__(self, parameters: Dict[str, Any], state: Dict[str, Any] = None):
        self.position_cap_usd = Decimal(str(parameters.get("positionCapUsd", 20)))
        self.adx_threshold = Decimal(str(parameters.get("adxThreshold", 25)))
        self.lookback_period = int(parameters.get("lookbackPeriod", 20))
        self.trailing_stop_percent = float(parameters.get("trailingStopPercent", 2.0))
        self.max_consecutive_losses = int(parameters.get("maxConsecutiveLosses", 3))
        self.cooldown_hours = int(parameters.get("cooldownHours", 24))
        
        self.state = state or {
            "consecutive_losses": 0,
            "cooldown_until": None,
            "last_loss_at": None,
        }
        
        # Price history for indicators
        self.highs: List[Decimal] = []
        self.lows: List[Decimal] = []
        self.closes: List[Decimal] = []
        
        # Track highest price since entry for trailing stop
        self.entry_price: Optional[Decimal] = None
        self.highest_since_entry: Optional[Decimal] = None
    
    def get_required_history(self) -> int:
        return self.lookback_period + 15  # Extra for ADX calculation
    
    def _is_in_cooldown(self, current_time_ms: int) -> bool:
        if not self.state.get("cooldown_until"):
            return False
        
        cooldown_until = self.state["cooldown_until"]
        if isinstance(cooldown_until, str):
            cooldown_until = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00")).timestamp() * 1000
        
        return current_time_ms < cooldown_until
    
    def _calculate_position_size(self, price: Decimal) -> Decimal:
        if price <= 0:
            return Decimal("0")
        return self.position_cap_usd / price
    
    def on_data(self, data: MarketData, positions: List[Position]) -> Optional[Signal]:
        # Update price history
        self.highs.append(data.high)
        self.lows.append(data.low)
        self.closes.append(data.close)
        
        # Keep history bounded
        max_history = self.lookback_period + 20
        if len(self.closes) > max_history:
            self.highs = self.highs[-max_history:]
            self.lows = self.lows[-max_history:]
            self.closes = self.closes[-max_history:]
        
        # Check cooldown
        if self._is_in_cooldown(data.timestamp):
            return None
        
        # Check circuit breaker
        if self.state.get("consecutive_losses", 0) >= self.max_consecutive_losses:
            return None
        
        # Need enough data
        if len(self.closes) < self.lookback_period + 10:
            return None
        
        # Calculate ADX
        adx_result = calculate_adx(self.highs, self.lows, self.closes, period=14)
        if not adx_result:
            return None
        
        adx, plus_di, minus_di = adx_result
        trend = get_trend_direction(adx, plus_di, minus_di, self.adx_threshold)
        
        # Check for existing position
        existing_position = None
        for pos in positions:
            if pos.symbol == data.symbol:
                existing_position = pos
                break
        
        # If we have a position, check trailing stop
        if existing_position:
            if self.highest_since_entry is None:
                self.highest_since_entry = data.high
            else:
                self.highest_since_entry = max(self.highest_since_entry, data.high)
            
            # Trailing stop
            stop_price = self.highest_since_entry * Decimal(str(1 - self.trailing_stop_percent / 100))
            
            if data.close <= stop_price:
                return Signal(
                    symbol=data.symbol,
                    signal_type=SignalType.CLOSE_LONG,
                    quantity=existing_position.quantity,
                    confidence=0.8,
                    reason=f"Trailing stop hit at {stop_price:.2f}"
                )
            
            # Also check if trend has reversed
            if trend == "BEARISH" and is_trending(adx, self.adx_threshold):
                return Signal(
                    symbol=data.symbol,
                    signal_type=SignalType.CLOSE_LONG,
                    quantity=existing_position.quantity,
                    confidence=0.7,
                    reason=f"Trend reversal: ADX={adx:.1f}, trend={trend}"
                )
            
            return None
        
        # No position - check for entry
        if not is_trending(adx, self.adx_threshold):
            return None  # No clear trend
        
        if trend != "BULLISH":
            return None  # Only trading bullish trends for now
        
        # Check for breakout above recent high
        recent_high = max(self.highs[-self.lookback_period:-1])
        
        if data.close > recent_high:
            position_size = self._calculate_position_size(data.close)
            self.entry_price = data.close
            self.highest_since_entry = data.high
            
            return Signal(
                symbol=data.symbol,
                signal_type=SignalType.BUY,
                quantity=position_size,
                confidence=min(0.85, float(adx) / 50),  # Higher ADX = more confidence
                reason=f"Breakout above {recent_high:.2f}, ADX={adx:.1f}, trend={trend}"
            )
        
        return None
    
    def on_position_close(self, pnl: Decimal):
        if pnl < 0:
            self.state["consecutive_losses"] = self.state.get("consecutive_losses", 0) + 1
            self.state["last_loss_at"] = int(datetime.now().timestamp() * 1000)
            
            if self.state["consecutive_losses"] >= self.max_consecutive_losses:
                cooldown_end = datetime.now() + timedelta(hours=self.cooldown_hours)
                self.state["cooldown_until"] = cooldown_end.isoformat()
        else:
            self.state["consecutive_losses"] = 0
        
        # Reset tracking
        self.entry_price = None
        self.highest_since_entry = None


from datetime import timedelta
