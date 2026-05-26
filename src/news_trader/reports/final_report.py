from __future__ import annotations

from pathlib import Path

from news_trader.signals.adaptive import load_adaptive_state
from news_trader.storage import Store
from news_trader.trading.portfolio import mark_to_market


def print_report(db_path: Path, starting_cash: float) -> None:
    store = Store(db_path, starting_cash)
    mark = mark_to_market(store)
    total_return = ((mark.equity / starting_cash) - 1.0) if starting_cash else 0.0
    print("Paper-trading report")
    print(f"Cash: ${mark.cash:.2f}")
    print(f"Equity: ${mark.equity:.2f}")
    print(f"Return: {total_return:.2%}")
    for symbol in ("SPY", "QQQ"):
        start = store.get_state(f"benchmark_start_{symbol}")
        last = store.get_state(f"benchmark_last_{symbol}")
        if start and last and float(start) > 0:
            benchmark_return = (float(last) / float(start)) - 1.0
            print(f"{symbol} benchmark since bot start: {benchmark_return:.2%}")
    print(f"Gross exposure: ${mark.gross_exposure:.2f}")
    adaptive = load_adaptive_state(store)
    print("Adaptive state:")
    print(f"  confidence adjustment: {adaptive.confidence_adjustment:+.2f}")
    print(f"  position size multiplier: {adaptive.position_size_multiplier:.2f}")
    print(f"  gross exposure multiplier: {adaptive.max_gross_exposure_multiplier:.2f}")
    print(f"  reason: {adaptive.reason}")
    print("Positions:")
    positions = store.all_positions()
    if not positions:
        print("  None")
    for row in positions:
        qty = float(row["quantity"])
        side = "long" if qty > 0 else "short"
        last = mark.prices.get(row["ticker"], float(row["avg_price"]))
        avg = float(row["avg_price"])
        pnl = (last - avg) * qty
        print(f"  {row['ticker']}: {side} {abs(qty):.4f} shares @ avg ${avg:.2f}, last ${last:.2f}, P/L ${pnl:.2f}")
    trade_count = store.conn.execute("select count(*) as n from trades").fetchone()["n"]
    event_count = store.conn.execute("select count(*) as n from events").fetchone()["n"]
    decision_count = store.conn.execute("select count(*) as n from decisions").fetchone()["n"]
    source_run_count = store.conn.execute("select count(*) as n from source_runs").fetchone()["n"]
    print(f"Events stored: {event_count}")
    print(f"Decisions stored: {decision_count}")
    print(f"Trades stored: {trade_count}")
    print(f"Source runs logged: {source_run_count}")
    print("Recent source run statuses:")
    rows = store.conn.execute(
        """
        select run_id, source_id, status, items_seen, error
        from source_runs
        order by id desc
        limit 8
        """
    ).fetchall()
    for row in rows:
        suffix = f" ({row['error']})" if row["error"] else ""
        print(f"  {row['source_id']}: {row['status']}, items {row['items_seen']}{suffix}")
