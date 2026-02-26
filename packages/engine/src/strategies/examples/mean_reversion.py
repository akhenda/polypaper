"""Mean Reversion Strategy - trades bounces from Bollinger Bands."""
from decimal import Decimal
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import Strategy, StrategyMetadata, MarketData, Position, Signal, SignalType
from indicators.bollinger import calculate_bollinger_bands, mean_reversion_signal, is_squeeze


class MeanReversionStrategy(Strategy):
    """
    Mean Reversion / Divergence Strategy
    
    - Uses Bollinger Bands for entry signals
    - Buys at lower band, sells at upper band
    - Avoids entries during squeeze (low volatility)
    - Quick profit targets (reversion to mean)
    """
    
    @classmethod
    def metadata(cls) -> StrategyMetadata:
        return StrategyMetadata(
            id="mean-reversion-v1",
            name="Mean Reversion",
            description="Trades mean reversion using Bollinger Bands with volatility filter",
            version="1.0.0",
            supported_markets=["CRYPTO"],
            parameters={
                "positionCapUsd": {"type": "number", "default": 20, "description": "Maximum position size in USD"},
                "bbPeriod": {"type": "number", "default": 20, "description": "Bollinger Band period"},
                "bbStdDev": {"type": "number", "default": 2.0, "description": "Standard deviations"},
                "minBandWidth": {"type": "number", "default": 5.0, "description": "Minimum bandwidth % to trade"},
                "takeProfitPercent": {"type": "number", "default": 2.0, "description": "Profit target %"},
                "stopLossPercent": {"type": "number", "default": 2.0, "description": "Stop loss %"},
                "maxConsecutiveLosses": {"type": "number", "default": 3, "description": "Circuit breaker threshold"},
                "cooldownHours": {"type": "number", "default": 12, "description": "Cooldown period"},
                "intervalMinutes": {"type": "number", "default": 15, "description": "Strategy interval (15m)"},
            }
        )
    
    def __init__(self, parameters: Dict[str, Any], state: Dict[str, Any] = None):
        self.position_cap_usd = Decimal(str(parameters.get("positionCapUsd", 20)))
        self.bb_period = int(parameters.get("bbPeriod", 20))
        self.bb_std_dev = float(parameters.get("bbStdDev", 2.0))
        self.min_band_width = Decimal(str(parameters.get("minBandWidth", 5.0)))
        self.take_profit_percent = float(parameters.get("takeProfitPercent", 2.0))
        self.stop_loss_percent = float(parameters.get("stopLossPercent", 2.0))
        self.max_consecutive_losses = int(parameters.get("maxConsecutiveLosses", 3))
        self.cooldown_hours = int(parameters.get("cooldownHours", 12))
        
        self.state = state or {
            "consecutive_losses": 0,
            "cooldown_until": None,
            "last_loss_at": None,
        }
        
        self.closes: List[Decimal] = []
        self.entry_price: Optional[Decimal] = None
        self.target_price: Optional[Decimal] = None
    
    def get_required_history(self) -> int:
        return self.bb_period + 5
    
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
        self.closes.append(data.close)
        
        max_history = self.bb_period + 10
        if len(self.closes) > max_history:
            self.closes = self.closes[-max_history:]
        
        # Check cooldown
        if self._is_in_cooldown(data.timestamp):
            return None
        
        # Check circuit breaker
        if self.state.get("consecutive_losses", 0) >= self.max_consecutive_losses:
            return None
        
        # Need enough data
        if len(self.closes) < self.bb_period:
            return None
        
        # Calculate Bollinger Bands
        bb_result = calculate_bollinger_bands(self.closes, self.bb_period, self.bb_std_dev)
        if not bb_result:
            return None
        
        upper, middle, lower, bandwidth = bb_result
        
        # Check for existing position
        existing_position = None
        for pos in positions:
            if pos.symbol == data.symbol:
                existing_position = pos
                break
        
        # If we have a position, check take profit / stop loss / target
        if existing_position:
            entry = existing_position.avg_entry_price
            pnl_percent = float((data.close - entry) / entry * 100)
            
            # Take profit
            if pnl_percent >= self.take_profit_percent:
                return Signal(
                    symbol=data.symbol,
                    signal_type=SignalType.CLOSE_LONG,
                    quantity=existing_position.quantity,
                    confidence=0.8,
                    reason=f"Take profit: {pnl_percent:.1f}% >= {self.take_profit_percent}%"
                )
            
            # Stop loss
            if pnl_percent <= -self.stop_loss_percent:
                return Signal(
                    symbol=data.symbol,
                    signal_type=SignalType.CLOSE_LONG,
                    quantity=existing_position.quantity,
                    confidence=0.8,
                    reason=f"Stop loss: {pnl_percent:.1f}% <= -{self.stop_loss_percent}%"
                )
            
            # Target: middle band (mean reversion)
            if data.close >= middle * Decimal("0.98"):  # Within 2% of middle
                return Signal(
                    symbol=data.symbol,
                    signal_type=SignalType.CLOSE_LONG,
                    quantity=existing_position.quantity,
                    confidence=0.7,
                    reason=f"Reversion to mean: price near middle band {middle:.2f}"
                )
            
            return None
        
        # No position - check for entry
        
        # Avoid trading in squeeze (low volatility)
        if is_squeeze(bandwidth, self.min_band_width):
            return None
        
        # Check for mean reversion signal
        signal_type = mean_reversion_signal(data.close, upper, middle, lower, self.min_band_width)
        
        if signal_type == "BUY":
            # Price near lower band - expect reversion up
            position_size = self._calculate_position_size(data.close)
            self.entry_price = data.close
            self.target_price = middle
            
            return Signal(
                symbol=data.symbol,
                signal_type=SignalType.BUY,
                quantity=position_size,
                confidence=min(0.8, float(bandwidth) / 10),  # Higher volatility = more confidence
                reason=f"Mean reversion buy: price={data.close:.2f} near lower band {lower:.2f}, bandwidth={bandwidth:.1f}%"
            )
        
        # Note: We don't short in paper trading for now
        # if signal_type == "SELL": ...
        
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
        
        self.entry_price = None
        self.target_price = None
