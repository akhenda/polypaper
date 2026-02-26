"""Late Entry Strategy - enters during favorable volatility with circuit breaker."""
from decimal import Decimal
from typing import Dict, Any, List, Optional
from ..base import Strategy, StrategyMetadata, MarketData, Position, Signal, SignalType
import math


class LateEntryStrategy(Strategy):
    """
    Late Entry Strategy
    
    - Enters trades only during favorable volatility conditions
    - Position cap (default $20)
    - Circuit breaker: stops after 3 consecutive losses, 24h cooldown
    """
    
    @classmethod
    def metadata(cls) -> StrategyMetadata:
        return StrategyMetadata(
            id="late-entry-v1",
            name="Late Entry",
            description="Enters trades during favorable volatility conditions with position cap and circuit breaker",
            version="1.0.0",
            supported_markets=["CRYPTO"],
            parameters={
                "positionCapUsd": {"type": "number", "default": 20, "description": "Maximum position size in USD"},
                "volatilityThreshold": {"type": "number", "default": 0.015, "description": "Minimum volatility to trigger entry"},
                "maxConsecutiveLosses": {"type": "number", "default": 3, "description": "Circuit breaker threshold"},
                "cooldownHours": {"type": "number", "default": 24, "description": "Cooldown period after circuit breaker"},
                "takeProfitPercent": {"type": "number", "default": 5.0, "description": "Take profit threshold %"},
                "stopLossPercent": {"type": "number", "default": 3.0, "description": "Stop loss threshold %"},
            }
        )
    
    def __init__(self, parameters: Dict[str, Any], state: Dict[str, Any] = None):
        self.position_cap_usd = Decimal(str(parameters.get("positionCapUsd", 20)))
        self.volatility_threshold = float(parameters.get("volatilityThreshold", 0.015))
        self.max_consecutive_losses = int(parameters.get("maxConsecutiveLosses", 3))
        self.cooldown_hours = int(parameters.get("cooldownHours", 24))
        self.take_profit_percent = float(parameters.get("takeProfitPercent", 5.0))
        self.stop_loss_percent = float(parameters.get("stopLossPercent", 3.0))
        
        # State from DB
        self.state = state or {
            "consecutive_losses": 0,
            "cooldown_until": None,
            "last_loss_at": None,
        }
        
        self.price_history: List[Decimal] = []
        self.lookback = 10  # candles needed for volatility calc
    
    def get_required_history(self) -> int:
        return self.lookback + 1
    
    def _calculate_volatility(self) -> float:
        """Calculate price volatility as std dev of returns."""
        if len(self.price_history) < self.lookback:
            return 0.0
        
        recent = [float(p) for p in self.price_history[-self.lookback:]]
        returns = [(recent[i] - recent[i-1]) / recent[i-1] for i in range(1, len(recent))]
        
        if not returns:
            return 0.0
        
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance)
    
    def _is_in_cooldown(self, current_time_ms: int) -> bool:
        """Check if we're in cooldown period."""
        if not self.state.get("cooldown_until"):
            return False
        
        cooldown_until = self.state["cooldown_until"]
        if isinstance(cooldown_until, str):
            from datetime import datetime
            cooldown_until = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00")).timestamp() * 1000
        
        return current_time_ms < cooldown_until
    
    def _calculate_position_size(self, price: Decimal) -> Decimal:
        """Calculate position size based on cap."""
        if price <= 0:
            return Decimal("0")
        return self.position_cap_usd / price
    
    def on_data(self, data: MarketData, positions: List[Position]) -> Optional[Signal]:
        """Process new data and potentially generate a signal."""
        self.price_history.append(data.close)
        
        # Keep history bounded
        if len(self.price_history) > self.lookback + 5:
            self.price_history = self.price_history[-(self.lookback + 5):]
        
        # Check cooldown
        if self._is_in_cooldown(data.timestamp):
            return None
        
        # Check circuit breaker
        if self.state.get("consecutive_losses", 0) >= self.max_consecutive_losses:
            return None
        
        # Check for existing position
        existing_position = None
        for pos in positions:
            if pos.symbol == data.symbol:
                existing_position = pos
                break
        
        # If we have a position, check take profit / stop loss
        if existing_position:
            entry_price = existing_position.avg_entry_price
            current_price = data.close
            pnl_percent = float((current_price - entry_price) / entry_price * 100)
            
            if pnl_percent >= self.take_profit_percent:
                return Signal(
                    symbol=data.symbol,
                    signal_type=SignalType.CLOSE_LONG,
                    quantity=existing_position.quantity,
                    confidence=0.9,
                    reason=f"Take profit hit: {pnl_percent:.1f}% >= {self.take_profit_percent}%"
                )
            
            if pnl_percent <= -self.stop_loss_percent:
                return Signal(
                    symbol=data.symbol,
                    signal_type=SignalType.CLOSE_LONG,
                    quantity=existing_position.quantity,
                    confidence=0.9,
                    reason=f"Stop loss hit: {pnl_percent:.1f}% <= -{self.stop_loss_percent}%"
                )
            
            # Hold position
            return None
        
        # Check volatility for entry
        volatility = self._calculate_volatility()
        
        if volatility < self.volatility_threshold:
            return None  # Not volatile enough
        
        # Calculate momentum (simple: price > recent average)
        if len(self.price_history) < 3:
            return None
        
        recent_avg = sum(self.price_history[-5:]) / 5
        if data.close <= recent_avg:
            return None  # Not trending up
        
        # Entry signal
        position_size = self._calculate_position_size(data.close)
        
        return Signal(
            symbol=data.symbol,
            signal_type=SignalType.BUY,
            quantity=position_size,
            confidence=min(0.8, volatility * 10),  # Higher volatility = more confidence
            reason=f"Volatility {volatility*100:.2f}% > threshold {self.volatility_threshold*100:.1f}%, trending up"
        )
    
    def on_position_close(self, pnl: Decimal):
        """Called when a position is closed with realized PnL."""
        if pnl < 0:
            self.state["consecutive_losses"] = self.state.get("consecutive_losses", 0) + 1
            self.state["last_loss_at"] = int(datetime.now().timestamp() * 1000)
            
            if self.state["consecutive_losses"] >= self.max_consecutive_losses:
                from datetime import datetime, timedelta
                cooldown_end = datetime.now() + timedelta(hours=self.cooldown_hours)
                self.state["cooldown_until"] = cooldown_end.isoformat()
        else:
            self.state["consecutive_losses"] = 0


# Import datetime at module level
from datetime import datetime
