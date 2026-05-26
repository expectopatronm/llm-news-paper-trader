from __future__ import annotations

import argparse
from pathlib import Path
import time

from news_trader.config import load_config
from news_trader.codex_handoff import collect_for_codex, execute_codex_classifications
from news_trader.env import load_dotenv
from news_trader.market_hours import describe_market_window, is_us_market_open
from news_trader.pipeline import run_once
from news_trader.reports.final_report import print_report
from news_trader.reports.performance_review import run_performance_review


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LLM-assisted news paper trader")
    parser.add_argument("--db", default="data/bot.sqlite", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-once", help="Run one scan/decision/trade cycle")
    sub.add_parser("codex-collect", help="Collect fixed-source events for Codex classification")
    sub.add_parser("codex-execute", help="Execute validated Codex classifications")
    sub.add_parser("loop", help="Run forever at the configured interval")
    sub.add_parser("report", help="Print portfolio/event/trade summary")
    sub.add_parser("review", help="Review performance and update adaptive strategy state")
    sub.add_parser("market-hours", help="Show today's US market hours in local time")
    sub.add_parser("market-status", help="Print OPEN or CLOSED for regular U.S. market hours")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config()
    load_dotenv(config.root / ".env")
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = config.root / db_path

    if args.command == "market-hours":
        print("Regular US market hours today:")
        print(describe_market_window(config.schedule.timezone, config.schedule.market_timezone))
        return

    if args.command == "market-status":
        print("OPEN" if is_us_market_open(market_timezone=config.schedule.market_timezone) else "CLOSED")
        return

    if args.command == "report":
        print_report(db_path, config.trading.starting_cash_usd)
        return

    if args.command == "review":
        run_performance_review(db_path, config.trading.starting_cash_usd)
        return

    if args.command == "run-once":
        run_once(config, db_path)
        return

    if args.command == "codex-collect":
        collect_for_codex(config, db_path)
        return

    if args.command == "codex-execute":
        execute_codex_classifications(config, db_path)
        return

    if args.command == "loop":
        interval_seconds = config.schedule.interval_minutes * 60
        print(f"Starting loop. Interval: {config.schedule.interval_minutes} minutes.")
        print(f"US regular market hours in {config.schedule.timezone}:")
        print(describe_market_window(config.schedule.timezone, config.schedule.market_timezone))
        while True:
            run_once(config, db_path)
            time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
