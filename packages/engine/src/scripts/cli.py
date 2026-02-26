#!/usr/bin/env python3
"""
Polypaper CLI Utilities

Commands:
    python -m scripts.cli backtest --strategy late-entry-v1 --days 30
    python -m scripts.cli ingest-polymarket --limit 20
    python -m scripts.cli status
"""
import argparse
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from decimal import Decimal
from datetime import datetime, timedelta

from strategies.examples import STRATEGY_REGISTRY
from backtest.runner import run_backtest, format_backtest_report
from data.polymarket import ingest_polymarket_markets, fetch_markets


DATABASE_URL = os.getenv("DATABASE_URL", "postgres://polypaper:polypaper@localhost:5432/polypaper")


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def cmd_backtest(args):
    """Run a backtest on historical data."""
    strategy_id = args.strategy
    days = args.days
    
    if strategy_id not in STRATEGY_REGISTRY:
        print(f"Unknown strategy: {strategy_id}")
        print(f"Available: {list(STRATEGY_REGISTRY.keys())}")
        return 1
    
    strategy_class = STRATEGY_REGISTRY[strategy_id]
    
    # Fetch historical candles from DB
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get market ID
            cur.execute("SELECT id FROM markets WHERE symbol = 'BTC-USD' LIMIT 1")
            row = cur.fetchone()
            if not row:
                print("No BTC-USD market found")
                return 1
            market_id = str(row["id"])
            
            # Fetch candles
            since = datetime.utcnow() - timedelta(days=days)
            cur.execute("""
                SELECT timestamp, open, high, low, close, volume
                FROM market_candles
                WHERE market_id = %s AND interval = '1m' AND timestamp >= %s
                ORDER BY timestamp ASC
            """, (market_id, since))
            rows = cur.fetchall()
    
    if not rows:
        print(f"No candles found in the last {days} days")
        return 1
    
    # Convert to candle format
    candles = [
        {
            "timestamp": int(r["timestamp"].timestamp() * 1000),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
            "symbol": "BTC-USD",
        }
        for r in rows
    ]
    
    print(f"Running backtest on {len(candles)} candles...")
    
    # Run backtest
    result = run_backtest(
        strategy_class,
        candles,
        parameters={"positionCapUsd": 20},
        initial_capital=Decimal("10000"),
        position_cap_usd=Decimal("20"),
    )
    
    print()
    print(format_backtest_report(result))
    
    # Save to DB
    if args.save:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO backtests 
                        (strategy_id, parameters, market_ids, start_date, end_date,
                         initial_capital, final_capital, total_return, max_drawdown,
                         win_rate, trade_count, equity_curve, trades, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'COMPLETED')
                """, (
                    strategy_id,
                    '{"positionCapUsd": 20}',
                    [market_id],
                    result.start_date,
                    result.end_date,
                    result.initial_capital,
                    result.final_capital,
                    result.total_return_pct,
                    result.max_drawdown_pct,
                    result.win_rate,
                    result.total_trades,
                    str([{"t": t, "e": float(e)} for t, e in result.equity_curve]),
                    str([{"timestamp": t.timestamp, "side": t.side, "price": float(t.price), 
                          "quantity": float(t.quantity), "pnl": float(t.pnl)} for t in result.trades]),
                ))
                conn.commit()
        print("\nBacktest saved to database.")
    
    return 0


def cmd_ingest_polymarket(args):
    """Ingest Polymarket markets."""
    limit = args.limit
    
    print(f"Fetching {limit} Polymarket markets...")
    
    with get_db() as conn:
        count = ingest_polymarket_markets(conn, limit=limit)
    
    print(f"Ingested {count} markets")
    return 0


def cmd_status(args):
    """Show system status."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Accounts
            cur.execute("SELECT COUNT(*) as count FROM accounts WHERE is_active = true")
            accounts = cur.fetchone()["count"]
            
            # Markets
            cur.execute("SELECT COUNT(*) as count FROM markets WHERE is_active = true")
            markets = cur.fetchone()["count"]
            
            # Strategy instances
            cur.execute("SELECT COUNT(*) as count FROM strategy_instances WHERE is_active = true")
            instances = cur.fetchone()["count"]
            
            # Positions
            cur.execute("SELECT COUNT(*) as count FROM positions WHERE is_open = true")
            positions = cur.fetchone()["count"]
            
            # Recent trades
            cur.execute("""
                SELECT COUNT(*) as count FROM trade_log 
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)
            recent_trades = cur.fetchone()["count"]
            
            # Strategy state
            cur.execute("""
                SELECT strategy_id, total_trades, winning_trades, total_pnl, consecutive_losses
                FROM strategy_state
                ORDER BY strategy_id
            """)
            states = cur.fetchall()
    
    print("=== Polypaper Status ===")
    print(f"Accounts: {accounts} active")
    print(f"Markets: {markets} active")
    print(f"Strategy Instances: {instances} active")
    print(f"Open Positions: {positions}")
    print(f"Trades (24h): {recent_trades}")
    print()
    
    if states:
        print("=== Strategy Performance ===")
        for s in states:
            win_rate = (s["winning_trades"] / s["total_trades"] * 100) if s["total_trades"] > 0 else 0
            print(f"  {s['strategy_id']}: {s['total_trades']} trades, {win_rate:.1f}% win rate, "
                  f"PnL: ${float(s['total_pnl']):.2f}, streak: {s['consecutive_losses']} losses")
    
    return 0


def main():
    parser = argparse.ArgumentParser(description="Polypaper CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # backtest command
    backtest_parser = subparsers.add_parser("backtest", help="Run a backtest")
    backtest_parser.add_argument("--strategy", "-s", default="late-entry-v1", help="Strategy ID")
    backtest_parser.add_argument("--days", "-d", type=int, default=30, help="Days of history")
    backtest_parser.add_argument("--save", action="store_true", help="Save results to DB")
    
    # ingest-polymarket command
    ingest_parser = subparsers.add_parser("ingest-polymarket", help="Ingest Polymarket markets")
    ingest_parser.add_argument("--limit", "-l", type=int, default=20, help="Max markets to fetch")
    
    # status command
    status_parser = subparsers.add_parser("status", help="Show system status")
    
    args = parser.parse_args()
    
    if args.command == "backtest":
        return cmd_backtest(args)
    elif args.command == "ingest-polymarket":
        return cmd_ingest_polymarket(args)
    elif args.command == "status":
        return cmd_status(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
