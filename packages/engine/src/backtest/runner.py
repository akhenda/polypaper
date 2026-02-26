"""
Backtest Runner (Phase 2C)

Runs strategies over historical data to evaluate performance.
Applies fees, slippage, and position caps.
"""
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
import math


@dataclass
class BacktestTrade:
    """Single trade record."""
    timestamp: int
    symbol: str
    side: str  # BUY or SELL
    quantity: Decimal
    price: Decimal
    pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")


@dataclass
class BacktestResult:
    """Complete backtest results."""
    strategy_id: str
    start_date: str
    end_date: str
    initial_capital: Decimal
    final_capital: Decimal
    total_return: Decimal
    total_return_pct: Decimal
    win_rate: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Optional[Decimal]
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Tuple[int, Decimal]] = field(default_factory=list)


class BacktestEngine:
    """
    Event-driven backtest engine.
    
    Features:
    - Fee calculation (default 0.1% per trade)
    - Slippage modeling
    - Position caps
    - Equity curve tracking
    - Performance metrics
    """
    
    def __init__(
        self,
        initial_capital: Decimal = Decimal("10000"),
        position_cap_usd: Decimal = Decimal("20"),
        fee_rate: Decimal = Decimal("0.001"),  # 0.1%
        slippage_rate: Decimal = Decimal("0.0005"),  # 0.05%
    ):
        self.initial_capital = initial_capital
        self.position_cap_usd = position_cap_usd
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        
        # State
        self.capital = initial_capital
        self.position: Optional[Dict[str, Any]] = None
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Tuple[int, Decimal]] = []
        self.peak_equity = initial_capital
        self.max_drawdown = Decimal("0")
    
    def reset(self):
        """Reset backtest state."""
        self.capital = self.initial_capital
        self.position = None
        self.trades = []
        self.equity_curve = []
        self.peak_equity = self.initial_capital
        self.max_drawdown = Decimal("0")
    
    def _apply_slippage(self, price: Decimal, is_buy: bool) -> Decimal:
        """Apply slippage to price."""
        slippage = price * self.slippage_rate
        if is_buy:
            return price + slippage  # Pay more when buying
        else:
            return price - slippage  # Receive less when selling
    
    def _calculate_fee(self, value: Decimal) -> Decimal:
        """Calculate trading fee."""
        return value * self.fee_rate
    
    def _calculate_position_size(self, price: Decimal) -> Decimal:
        """Calculate position size based on cap."""
        if price <= 0:
            return Decimal("0")
        return self.position_cap_usd / price
    
    def execute_buy(self, timestamp: int, symbol: str, price: Decimal, 
                    quantity: Optional[Decimal] = None) -> Optional[BacktestTrade]:
        """Execute a buy order."""
        if self.position is not None:
            return None  # Already have a position
        
        if quantity is None:
            quantity = self._calculate_position_size(price)
        
        # Apply slippage
        fill_price = self._apply_slippage(price, is_buy=True)
        
        # Check capital
        cost = quantity * fill_price
        if cost > self.capital:
            quantity = self.capital / fill_price
            cost = quantity * fill_price
        
        # Calculate fees
        fees = self._calculate_fee(cost)
        total_cost = cost + fees
        
        if total_cost > self.capital:
            return None
        
        # Execute
        self.capital -= total_cost
        self.position = {
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": fill_price,
            "entry_time": timestamp,
            "fees_paid": fees,
        }
        
        trade = BacktestTrade(
            timestamp=timestamp,
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            price=fill_price,
            fees=fees,
            slippage=(fill_price - price) * quantity,
        )
        self.trades.append(trade)
        
        return trade
    
    def execute_sell(self, timestamp: int, price: Decimal) -> Optional[BacktestTrade]:
        """Execute a sell order (close position)."""
        if self.position is None:
            return None
        
        # Apply slippage
        fill_price = self._apply_slippage(price, is_buy=False)
        
        quantity = self.position["quantity"]
        entry_price = self.position["entry_price"]
        
        # Calculate proceeds
        proceeds = quantity * fill_price
        fees = self._calculate_fee(proceeds)
        net_proceeds = proceeds - fees
        
        # Calculate PnL
        cost_basis = quantity * entry_price + self.position["fees_paid"]
        pnl = net_proceeds - cost_basis
        
        # Execute
        self.capital += net_proceeds
        self.position = None
        
        trade = BacktestTrade(
            timestamp=timestamp,
            symbol=self.position["symbol"] if self.position else "unknown",
            side="SELL",
            quantity=quantity,
            price=fill_price,
            pnl=pnl,
            fees=fees,
            slippage=(price - fill_price) * quantity,
        )
        self.trades.append(trade)
        
        return trade
    
    def update_equity(self, timestamp: int, current_price: Decimal):
        """Update equity curve and drawdown."""
        # Calculate total equity
        equity = self.capital
        if self.position:
            equity += self.position["quantity"] * current_price
        
        self.equity_curve.append((timestamp, equity))
        
        # Track drawdown
        if equity > self.peak_equity:
            self.peak_equity = equity
        
        drawdown = self.peak_equity - equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
    
    def get_results(self, strategy_id: str, start_date: str, end_date: str) -> BacktestResult:
        """Calculate final results."""
        # Calculate final equity (use last equity curve value or capital)
        final_capital = self.capital
        if self.equity_curve:
            final_capital = self.equity_curve[-1][1]
        
        # Total return
        total_return = final_capital - self.initial_capital
        total_return_pct = (total_return / self.initial_capital) * 100
        
        # Win rate
        sell_trades = [t for t in self.trades if t.side == "SELL"]
        winning_trades = sum(1 for t in sell_trades if t.pnl > 0)
        losing_trades = sum(1 for t in sell_trades if t.pnl <= 0)
        total_sells = len(sell_trades)
        win_rate = Decimal(str(winning_trades / total_sells * 100)) if total_sells > 0 else Decimal("0")
        
        # Max drawdown percentage
        max_drawdown_pct = (self.max_drawdown / self.peak_equity) * 100 if self.peak_equity > 0 else Decimal("0")
        
        # Sharpe ratio (simplified)
        sharpe_ratio = self._calculate_sharpe_ratio()
        
        return BacktestResult(
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            win_rate=win_rate,
            total_trades=len(sell_trades),
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            max_drawdown=self.max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            trades=self.trades,
            equity_curve=self.equity_curve,
        )
    
    def _calculate_sharpe_ratio(self, risk_free_rate: Decimal = Decimal("0.02")) -> Optional[Decimal]:
        """Calculate simplified Sharpe ratio."""
        if len(self.equity_curve) < 2:
            return None
        
        # Calculate returns
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev_equity = self.equity_curve[i-1][1]
            curr_equity = self.equity_curve[i][1]
            if prev_equity > 0:
                ret = float((curr_equity - prev_equity) / prev_equity)
                returns.append(ret)
        
        if len(returns) < 2:
            return None
        
        # Calculate mean and std
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance)
        
        if std_return == 0:
            return None
        
        # Annualized Sharpe (assuming daily data)
        annualized_return = mean_return * 252
        annualized_std = std_return * math.sqrt(252)
        
        sharpe = Decimal(str((annualized_return - float(risk_free_rate)) / annualized_std))
        return sharpe


def run_backtest(
    strategy_class,
    candles: List[Dict[str, Any]],
    parameters: Dict[str, Any],
    initial_capital: Decimal = Decimal("10000"),
    position_cap_usd: Decimal = Decimal("20"),
) -> BacktestResult:
    """
    Run a backtest on historical candle data.
    
    Args:
        strategy_class: Strategy class to test
        candles: List of candle dicts with keys: timestamp, open, high, low, close, volume
        parameters: Strategy parameters
        initial_capital: Starting capital
        position_cap_usd: Maximum position size
    
    Returns:
        BacktestResult with performance metrics
    """
    from strategies.base import MarketData, Position
    
    # Initialize
    strategy = strategy_class(parameters)
    engine = BacktestEngine(
        initial_capital=initial_capital,
        position_cap_usd=position_cap_usd,
    )
    
    # Sort candles by timestamp
    candles = sorted(candles, key=lambda x: x["timestamp"])
    
    # Determine date range
    start_date = datetime.fromtimestamp(candles[0]["timestamp"] / 1000).strftime("%Y-%m-%d")
    end_date = datetime.fromtimestamp(candles[-1]["timestamp"] / 1000).strftime("%Y-%m-%d")
    
    # Run through candles
    positions: List[Position] = []
    
    for candle in candles:
        # Create MarketData
        data = MarketData(
            symbol=candle.get("symbol", "BTC-USD"),
            timestamp=candle["timestamp"],
            open=Decimal(str(candle["open"])),
            high=Decimal(str(candle["high"])),
            low=Decimal(str(candle["low"])),
            close=Decimal(str(candle["close"])),
            volume=Decimal(str(candle.get("volume", 0))),
        )
        
        # Run strategy
        signal = strategy.on_data(data, positions)
        
        # Process signal
        if signal:
            if signal.signal_type.value == "BUY":
                trade = engine.execute_buy(
                    data.timestamp,
                    data.symbol,
                    data.close,
                    signal.quantity
                )
                if trade:
                    positions = [Position(
                        symbol=data.symbol,
                        side="LONG",
                        quantity=trade.quantity,
                        avg_entry_price=trade.price
                    )]
            
            elif signal.signal_type.value in ["SELL", "CLOSE_LONG"]:
                trade = engine.execute_sell(data.timestamp, data.close)
                if trade:
                    positions = []
        
        # Update equity
        engine.update_equity(data.timestamp, data.close)
    
    # Get results
    return engine.get_results(
        strategy_id=strategy.metadata().id,
        start_date=start_date,
        end_date=end_date
    )


def format_backtest_report(result: BacktestResult) -> str:
    """Format backtest result as human-readable report."""
    lines = [
        f"=== Backtest Report: {result.strategy_id} ===",
        f"Period: {result.start_date} to {result.end_date}",
        f"",
        f"Capital: {result.initial_capital:.2f} -> {result.final_capital:.2f}",
        f"Total Return: {result.total_return_pct:+.2f}%",
        f"",
        f"Trades: {result.total_trades}",
        f"  Wins: {result.winning_trades}",
        f"  Losses: {result.losing_trades}",
        f"  Win Rate: {result.win_rate:.1f}%",
        f"",
        f"Max Drawdown: {result.max_drawdown_pct:.2f}%",
    ]
    
    if result.sharpe_ratio:
        lines.append(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
    
    return "\n".join(lines)
