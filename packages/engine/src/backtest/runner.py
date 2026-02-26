"""
Backtest Runner (Phase 2C)

Runs strategies over historical data to evaluate performance.
Applies fees, slippage, and position caps.
"""
import os
import sys
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import uuid

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import MarketData, Position, Signal, SignalType
from strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Single trade in backtest."""
    entry_time: datetime
    exit_time: datetime
    symbol: str
    side: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal
    pnl_percent: float
    reason_entry: str
    reason_exit: str


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    strategy_id: str
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    final_capital: Decimal
    total_return: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Tuple[datetime, Decimal]] = field(default_factory=list)


class BacktestEngine:
    """Event-driven backtest engine."""
    
    def __init__(
        self,
        strategy_id: str,
        parameters: Dict[str, Any],
        initial_capital: Decimal = Decimal("10000"),
        position_cap_usd: Decimal = Decimal("20"),
        fee_percent: float = 0.1,  # 0.1% fee
        slippage_percent: float = 0.05,  # 0.05% slippage
    ):
        self.strategy_id = strategy_id
        self.parameters = parameters
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.position_cap_usd = position_cap_usd
        self.fee_percent = fee_percent
        self.slippage_percent = slippage_percent
        
        # Strategy instance
        strategy_class = STRATEGY_REGISTRY.get(strategy_id)
        if not strategy_class:
            raise ValueError(f"Unknown strategy: {strategy_id}")
        
        self.strategy = strategy_class(parameters)
        
        # State
        self.position: Optional[Position] = None
        self.entry_price: Optional[Decimal] = None
        self.entry_time: Optional[datetime] = None
        self.entry_reason: str = ""
        
        # Results
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Tuple[datetime, Decimal]] = []
        self.peak_equity = initial_capital
        self.max_drawdown = 0.0
    
    def _apply_slippage(self, price: Decimal, is_buy: bool) -> Decimal:
        """Apply slippage to price."""
        slippage = price * Decimal(str(self.slippage_percent / 100))
        if is_buy:
            return price + slippage  # Pay more on buy
        else:
            return price - slippage  # Receive less on sell
    
    def _calculate_fee(self, value: Decimal) -> Decimal:
        """Calculate trading fee."""
        return value * Decimal(str(self.fee_percent / 100))
    
    def _calculate_position_size(self, price: Decimal) -> Decimal:
        """Calculate position size based on cap."""
        effective_capital = min(self.capital, self.position_cap_usd)
        if price <= 0:
            return Decimal("0")
        return effective_capital / price
    
    def _execute_buy(self, data: MarketData, signal: Signal):
        """Execute buy signal in backtest."""
        if self.position is not None:
            return  # Already in position
        
        fill_price = self._apply_slippage(data.close, is_buy=True)
        quantity = self._calculate_position_size(fill_price)
        cost = quantity * fill_price
        fee = self._calculate_fee(cost)
        
        if cost + fee > self.capital:
            # Scale down
            quantity = (self.capital - fee) / fill_price
            cost = quantity * fill_price
        
        self.capital -= (cost + fee)
        self.position = Position(
            symbol=data.symbol,
            side="LONG",
            quantity=quantity,
            avg_entry_price=fill_price
        )
        self.entry_price = fill_price
        self.entry_time = datetime.fromtimestamp(data.timestamp / 1000)
        self.entry_reason = signal.reason
    
    def _execute_sell(self, data: MarketData, signal: Signal):
        """Execute sell signal in backtest."""
        if self.position is None:
            return  # No position to sell
        
        fill_price = self._apply_slippage(data.close, is_buy=False)
        proceeds = self.position.quantity * fill_price
        fee = self._calculate_fee(proceeds)
        
        self.capital += (proceeds - fee)
        
        # Calculate PnL
        pnl = proceeds - (self.position.quantity * self.entry_price)
        pnl_percent = float(pnl / (self.position.quantity * self.entry_price)) * 100
        
        trade = BacktestTrade(
            entry_time=self.entry_time,
            exit_time=datetime.fromtimestamp(data.timestamp / 1000),
            symbol=data.symbol,
            side="LONG",
            entry_price=self.entry_price,
            exit_price=fill_price,
            quantity=self.position.quantity,
            pnl=pnl,
            pnl_percent=pnl_percent,
            reason_entry=self.entry_reason,
            reason_exit=signal.reason
        )
        self.trades.append(trade)
        
        # Update drawdown
        current_equity = self.capital
        self.peak_equity = max(self.peak_equity, current_equity)
        drawdown = float((self.peak_equity - current_equity) / self.peak_equity) * 100
        self.max_drawdown = max(self.max_drawdown, drawdown)
        
        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.entry_reason = ""
    
    def on_data(self, data: MarketData):
        """Process new data point."""
        # Get signal from strategy
        positions = [self.position] if self.position else []
        signal = self.strategy.on_data(data, positions)
        
        if signal:
            if signal.signal_type == SignalType.BUY:
                self._execute_buy(data, signal)
            elif signal.signal_type in (SignalType.SELL, SignalType.CLOSE_LONG):
                self._execute_sell(data, signal)
        
        # Record equity
        equity = self.capital
        if self.position and self.entry_price:
            # Add unrealized PnL
            unrealized = self.position.quantity * (data.close - self.entry_price)
            equity += unrealized
        
        self.equity_curve.append((
            datetime.fromtimestamp(data.timestamp / 1000),
            equity
        ))
    
    def get_results(self) -> BacktestResult:
        """Get backtest results."""
        final_capital = self.equity_curve[-1][1] if self.equity_curve else self.initial_capital
        total_return = float((final_capital - self.initial_capital) / self.initial_capital) * 100
        
        winning = [t for t in self.trades if t.pnl > 0]
        losing = [t for t in self.trades if t.pnl <= 0]
        win_rate = len(winning) / len(self.trades) * 100 if self.trades else 0
        
        # Calculate Sharpe ratio (simplified)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                prev_equity = float(self.equity_curve[i-1][1])
                curr_equity = float(self.equity_curve[i][1])
                if prev_equity > 0:
                    returns.append((curr_equity - prev_equity) / prev_equity)
            
            if returns:
                avg_return = sum(returns) / len(returns)
                variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
                std_dev = variance ** 0.5
                # Annualized Sharpe (assuming daily data)
                sharpe = (avg_return * 252) / (std_dev * (252 ** 0.5)) if std_dev > 0 else 0
            else:
                sharpe = 0
        else:
            sharpe = 0
        
        return BacktestResult(
            strategy_id=self.strategy_id,
            start_date=self.equity_curve[0][0] if self.equity_curve else datetime.now(),
            end_date=self.equity_curve[-1][0] if self.equity_curve else datetime.now(),
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_trades=len(self.trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=win_rate,
            max_drawdown=self.max_drawdown,
            sharpe_ratio=round(sharpe, 2),
            trades=self.trades,
            equity_curve=self.equity_curve
        )


def run_backtest(
    strategy_id: str,
    parameters: Dict[str, Any],
    market_id: str,
    start_date: datetime,
    end_date: datetime,
    database_url: str = None,
) -> BacktestResult:
    """
    Run backtest for a strategy over historical data.
    
    Args:
        strategy_id: Strategy ID (e.g., 'late-entry-v1')
        parameters: Strategy parameters
        market_id: Market ID to backtest
        start_date: Start date
        end_date: End date
        database_url: Database connection URL
    
    Returns:
        BacktestResult with performance metrics
    """
    database_url = database_url or os.getenv("DATABASE_URL", "postgres://polypaper:polypaper@localhost:5432/polypaper")
    
    # Load historical candles
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT timestamp, open, high, low, close, volume 
                FROM market_candles 
                WHERE market_id = %s 
                  AND timestamp >= %s 
                  AND timestamp <= %s
                ORDER BY timestamp ASC
            """, (market_id, start_date, end_date))
            
            rows = cur.fetchall()
            
        if not rows:
            raise ValueError(f"No candles found for market {market_id} in date range")
        
        logger.info(f"Loaded {len(rows)} candles for backtest")
        
        # Create backtest engine
        engine = BacktestEngine(strategy_id, parameters)
        
        # Run through candles
        for row in rows:
            data = MarketData(
                symbol="",  # Will be filled by strategy
                timestamp=int(row["timestamp"].timestamp() * 1000),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"]))
            )
            engine.on_data(data)
        
        return engine.get_results()
    
    finally:
        conn.close()


def save_backtest_result(result: BacktestResult, market_ids: List[str], database_url: str = None):
    """Save backtest result to database."""
    database_url = database_url or os.getenv("DATABASE_URL")
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            # Convert equity curve to JSON
            equity_json = [
                {"time": t.isoformat(), "equity": float(e)}
                for t, e in result.equity_curve
            ]
            
            # Convert trades to JSON
            trades_json = [
                {
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "symbol": t.symbol,
                    "entry_price": float(t.entry_price),
                    "exit_price": float(t.exit_price),
                    "quantity": float(t.quantity),
                    "pnl": float(t.pnl),
                    "pnl_percent": t.pnl_percent,
                }
                for t in result.trades
            ]
            
            cur.execute("""
                INSERT INTO backtests 
                    (strategy_id, parameters, market_ids, start_date, end_date,
                     initial_capital, final_capital, total_return, sharpe_ratio,
                     max_drawdown, win_rate, trade_count, equity_curve, trades, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'COMPLETED')
                RETURNING id
            """, (
                result.strategy_id,
                json.dumps({}),
                market_ids,
                result.start_date,
                result.end_date,
                result.initial_capital,
                result.final_capital,
                result.total_return,
                result.sharpe_ratio,
                result.max_drawdown,
                result.win_rate,
                result.total_trades,
                json.dumps(equity_json),
                json.dumps(trades_json)
            ))
            
            conn.commit()
            row = cur.fetchone()
            return str(row["id"]) if row else None
    
    finally:
        conn.close()


if __name__ == "__main__":
    # Example: Run backtest from command line
    import argparse
    
    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument("--strategy", required=True, help="Strategy ID")
    parser.add_argument("--market", required=True, help="Market ID")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--save", action="store_true", help="Save results to DB")
    
    args = parser.parse_args()
    
    result = run_backtest(
        strategy_id=args.strategy,
        parameters={},
        market_id=args.market,
        start_date=datetime.strptime(args.start, "%Y-%m-%d"),
        end_date=datetime.strptime(args.end, "%Y-%m-%d"),
    )
    
    print(f"\n=== Backtest Results ===")
    print(f"Strategy: {result.strategy_id}")
    print(f"Period: {result.start_date.date()} to {result.end_date.date()}")
    print(f"Initial Capital: ${result.initial_capital:,.2f}")
    print(f"Final Capital: ${result.final_capital:,.2f}")
    print(f"Total Return: {result.total_return:.2f}%")
    print(f"Win Rate: {result.win_rate:.1f}%")
    print(f"Total Trades: {result.total_trades}")
    print(f"Max Drawdown: {result.max_drawdown:.2f}%")
    print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
    
    if args.save:
        backtest_id = save_backtest_result(result, [args.market])
        print(f"\nSaved to backtests table: {backtest_id}")
