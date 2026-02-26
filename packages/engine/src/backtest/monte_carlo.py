"""
Monte Carlo Robustness Analysis

Block bootstrap simulation for backtest robustness validation.
"""
import numpy as np
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloResult:
    """Results from Monte Carlo simulation."""
    num_simulations: int
    block_size: int
    
    # Final equity distribution
    equity_p5: float
    equity_p50: float
    equity_p95: float
    equity_mean: float
    equity_std: float
    
    # Max drawdown distribution
    drawdown_p5: float
    drawdown_p50: float
    drawdown_p95: float
    
    # Risk metrics
    prob_ruin: float  # Probability of equity < threshold
    prob_profit: float  # Probability of positive return
    
    # All simulation results
    all_final_equities: List[float]
    all_max_drawdowns: List[float]


def block_bootstrap(returns: List[float], block_size: int, num_simulations: int) -> List[List[float]]:
    """
    Generate block bootstrap samples from returns series.
    
    Args:
        returns: List of periodic returns (as decimals, e.g., 0.01 for 1%)
        block_size: Size of blocks to sample
        num_simulations: Number of simulations to run
    
    Returns:
        List of simulated return series
    """
    if len(returns) < block_size:
        # Fall back to simple bootstrap if not enough data
        block_size = 1
    
    n_returns = len(returns)
    simulations = []
    
    for _ in range(num_simulations):
        # Create a new series by sampling blocks
        sampled_returns = []
        
        while len(sampled_returns) < n_returns:
            # Random starting position for block
            start_idx = np.random.randint(0, n_returns - block_size + 1)
            block = returns[start_idx:start_idx + block_size]
            sampled_returns.extend(block)
        
        # Trim to original length
        sampled_returns = sampled_returns[:n_returns]
        simulations.append(sampled_returns)
    
    return simulations


def calculate_equity_curve(returns: List[float], initial_capital: float) -> Tuple[List[float], float]:
    """
    Calculate equity curve from returns series.
    
    Returns:
        Tuple of (equity_curve, max_drawdown)
    """
    equity = initial_capital
    equity_curve = [equity]
    peak = equity
    max_drawdown = 0.0
    
    for r in returns:
        equity *= (1 + r)
        equity_curve.append(equity)
        
        if equity > peak:
            peak = equity
        
        drawdown = (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)
    
    return equity_curve, max_drawdown


def run_monte_carlo(
    trade_returns: List[float],
    initial_capital: float = 10000,
    num_simulations: int = 1000,
    block_size: int = 5,
    ruin_threshold: float = 0.5  # 50% loss = ruin
) -> MonteCarloResult:
    """
    Run Monte Carlo robustness analysis using block bootstrap.
    
    Args:
        trade_returns: List of trade returns (as decimals)
        initial_capital: Starting capital
        num_simulations: Number of Monte Carlo simulations
        block_size: Block size for bootstrap
        ruin_threshold: Equity level considered "ruin" (as fraction of initial)
    
    Returns:
        MonteCarloResult with distribution statistics
    """
    if not trade_returns:
        logger.warning("No trade returns provided for Monte Carlo")
        return MonteCarloResult(
            num_simulations=0,
            block_size=block_size,
            equity_p5=initial_capital,
            equity_p50=initial_capital,
            equity_p95=initial_capital,
            equity_mean=initial_capital,
            equity_std=0,
            drawdown_p5=0,
            drawdown_p50=0,
            drawdown_p95=0,
            prob_ruin=0,
            prob_profit=0,
            all_final_equities=[],
            all_max_drawdowns=[]
        )
    
    # Run block bootstrap
    simulations = block_bootstrap(trade_returns, block_size, num_simulations)
    
    # Calculate final equity and max drawdown for each simulation
    final_equities = []
    max_drawdowns = []
    
    for sim_returns in simulations:
        equity_curve, max_dd = calculate_equity_curve(sim_returns, initial_capital)
        final_equities.append(equity_curve[-1])
        max_drawdowns.append(max_dd * 100)  # Convert to percentage
    
    # Calculate statistics
    equities_arr = np.array(final_equities)
    drawdowns_arr = np.array(max_drawdowns)
    
    # Probability of ruin
    ruin_level = initial_capital * ruin_threshold
    prob_ruin = sum(1 for e in final_equities if e < ruin_level) / len(final_equities)
    
    # Probability of profit
    prob_profit = sum(1 for e in final_equities if e > initial_capital) / len(final_equities)
    
    return MonteCarloResult(
        num_simulations=num_simulations,
        block_size=block_size,
        equity_p5=float(np.percentile(equities_arr, 5)),
        equity_p50=float(np.percentile(equities_arr, 50)),
        equity_p95=float(np.percentile(equities_arr, 95)),
        equity_mean=float(np.mean(equities_arr)),
        equity_std=float(np.std(equities_arr)),
        drawdown_p5=float(np.percentile(drawdowns_arr, 5)),
        drawdown_p50=float(np.percentile(drawdowns_arr, 50)),
        drawdown_p95=float(np.percentile(drawdowns_arr, 95)),
        prob_ruin=prob_ruin,
        prob_profit=prob_profit,
        all_final_equities=final_equities,
        all_max_drawdowns=max_drawdowns
    )


def run_monte_carlo_from_equity_curve(
    equity_curve: List[float],
    num_simulations: int = 1000,
    block_size: int = 5,
    ruin_threshold: float = 0.5
) -> MonteCarloResult:
    """
    Run Monte Carlo from an existing equity curve.
    
    Converts equity curve to returns, then runs bootstrap.
    """
    if len(equity_curve) < 2:
        return run_monte_carlo([], 0, num_simulations, block_size, ruin_threshold)
    
    # Convert equity curve to returns
    returns = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i-1] > 0:
            r = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
            returns.append(r)
    
    initial = equity_curve[0] if equity_curve else 10000
    
    return run_monte_carlo(returns, initial, num_simulations, block_size, ruin_threshold)


if __name__ == "__main__":
    # Test with sample returns
    np.random.seed(42)
    
    # Simulate trade returns: mostly small wins, occasional big losses
    returns = []
    for _ in range(100):
        if np.random.random() < 0.6:
            returns.append(np.random.uniform(0.01, 0.05))  # Win
        else:
            returns.append(np.random.uniform(-0.08, -0.02))  # Loss
    
    result = run_monte_carlo(returns, initial_capital=10000, num_simulations=1000)
    
    print("=== Monte Carlo Results ===")
    print(f"Simulations: {result.num_simulations}")
    print(f"Block size: {result.block_size}")
    print()
    print(f"Final Equity:")
    print(f"  P5:  ${result.equity_p5:,.2f}")
    print(f"  P50: ${result.equity_p50:,.2f}")
    print(f"  P95: ${result.equity_p95:,.2f}")
    print()
    print(f"Max Drawdown:")
    print(f"  P5:  {result.drawdown_p5:.1f}%")
    print(f"  P50: {result.drawdown_p50:.1f}%")
    print(f"  P95: {result.drawdown_p95:.1f}%")
    print()
    print(f"Prob Ruin:   {result.prob_ruin * 100:.1f}%")
    print(f"Prob Profit: {result.prob_profit * 100:.1f}%")
