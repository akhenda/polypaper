"""
Walk-Forward Validation

Rolling window validation for strategy parameter optimization.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import itertools

from .runner import BacktestEngine, BacktestResult, run_backtest

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardResult:
    """Results from walk-forward validation."""
    strategy_id: str
    train_window_days: int
    test_window_days: int
    num_folds: int
    
    # Aggregate out-of-sample metrics
    total_return: float
    win_rate: float
    max_drawdown: float
    profit_factor: float
    
    # Per-fold results
    fold_results: List[Dict[str, Any]]
    
    # Best parameters per fold
    parameter_history: List[Dict[str, Any]]


def generate_parameter_grid(param_ranges: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """Generate all parameter combinations from ranges."""
    if not param_ranges:
        return [{}]
    
    keys = list(param_ranges.keys())
    values = [param_ranges[k] for k in keys]
    
    combinations = []
    for combo in itertools.product(*values):
        combinations.append(dict(zip(keys, combo)))
    
    return combinations


def optimize_parameters(
    strategy_id: str,
    base_params: Dict[str, Any],
    param_ranges: Dict[str, List[Any]],
    market_id: str,
    start_date: datetime,
    end_date: datetime,
    metric: str = "total_return"
) -> Tuple[Dict[str, Any], float]:
    """
    Find best parameters on a training window.
    
    Args:
        strategy_id: Strategy to optimize
        base_params: Base parameters (merged with grid params)
        param_ranges: Dict of param_name -> list of values to try
        market_id: Market to test on
        start_date: Start of training window
        end_date: End of training window
        metric: Metric to optimize ("total_return", "sharpe", "win_rate")
    
    Returns:
        Tuple of (best_params, best_metric_value)
    """
    grid = generate_parameter_grid(param_ranges)
    
    best_params = base_params.copy()
    best_value = float("-inf")
    
    for params in grid:
        # Merge with base params
        test_params = {**base_params, **params}
        
        try:
            result = run_backtest(
                strategy_id=strategy_id,
                parameters=test_params,
                market_id=market_id,
                start_date=start_date,
                end_date=end_date
            )
            
            # Get metric value
            if metric == "total_return":
                value = result.total_return
            elif metric == "sharpe":
                value = result.sharpe_ratio
            elif metric == "win_rate":
                value = result.win_rate
            else:
                value = result.total_return
            
            if value > best_value:
                best_value = value
                best_params = test_params.copy()
                
        except Exception as e:
            logger.warning(f"Parameter test failed: {e}")
            continue
    
    return best_params, best_value


def run_walk_forward(
    strategy_id: str,
    base_params: Dict[str, Any],
    param_ranges: Dict[str, List[Any]],
    market_id: str,
    start_date: datetime,
    end_date: datetime,
    train_window_days: int = 60,
    test_window_days: int = 30,
    optimize_metric: str = "total_return"
) -> WalkForwardResult:
    """
    Run walk-forward validation.
    
    Splits time into rolling windows, optimizes on train, tests on test.
    
    Args:
        strategy_id: Strategy to validate
        base_params: Base parameters
        param_ranges: Parameter ranges for optimization (empty = no optimization)
        market_id: Market ID
        start_date: Overall start date
        end_date: Overall end date
        train_window_days: Size of training window
        test_window_days: Size of test window
        optimize_metric: Metric to optimize in training
    
    Returns:
        WalkForwardResult with out-of-sample metrics
    """
    total_days = (end_date - start_date).days
    window_size = train_window_days + test_window_days
    num_folds = max(1, total_days // test_window_days - 1)
    
    fold_results = []
    parameter_history = []
    
    all_test_returns = []
    all_test_trades = 0
    all_test_wins = 0
    total_drawdown = 0
    
    for fold in range(num_folds):
        # Calculate window positions
        train_start = start_date + timedelta(days=fold * test_window_days)
        train_end = train_start + timedelta(days=train_window_days)
        test_start = train_end
        test_end = test_start + timedelta(days=test_window_days)
        
        if test_end > end_date:
            break
        
        logger.info(f"Fold {fold + 1}: train {train_start.date()} to {train_end.date()}, "
                   f"test {test_start.date()} to {test_end.date()}")
        
        # Optimize on training window (or use base params if no ranges)
        if param_ranges:
            best_params, _ = optimize_parameters(
                strategy_id, base_params, param_ranges,
                market_id, train_start, train_end, optimize_metric
            )
        else:
            best_params = base_params.copy()
        
        parameter_history.append(best_params)
        
        # Test on test window
        try:
            test_result = run_backtest(
                strategy_id=strategy_id,
                parameters=best_params,
                market_id=market_id,
                start_date=test_start,
                end_date=test_end
            )
            
            fold_results.append({
                "fold": fold + 1,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "params": best_params,
                "total_return": test_result.total_return,
                "win_rate": test_result.win_rate,
                "max_drawdown": test_result.max_drawdown,
                "num_trades": test_result.total_trades,
                "winning_trades": test_result.winning_trades,
            })
            
            all_test_returns.append(test_result.total_return)
            all_test_trades += test_result.total_trades
            all_test_wins += test_result.winning_trades
            total_drawdown = max(total_drawdown, test_result.max_drawdown)
            
        except Exception as e:
            logger.warning(f"Fold {fold + 1} test failed: {e}")
    
    # Calculate aggregate metrics
    total_return = sum(all_test_returns)
    win_rate = (all_test_wins / all_test_trades * 100) if all_test_trades > 0 else 0
    
    # Calculate profit factor
    gross_profit = sum(r for r in all_test_returns if r > 0)
    gross_loss = abs(sum(r for r in all_test_returns if r < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0
    
    return WalkForwardResult(
        strategy_id=strategy_id,
        train_window_days=train_window_days,
        test_window_days=test_window_days,
        num_folds=len(fold_results),
        total_return=total_return,
        win_rate=win_rate,
        max_drawdown=total_drawdown,
        profit_factor=profit_factor,
        fold_results=fold_results,
        parameter_history=parameter_history
    )


if __name__ == "__main__":
    from datetime import datetime
    
    # Example: Walk-forward with no parameter optimization
    print("Walk-forward validation example")
    print("(Would need real market data to run)")
