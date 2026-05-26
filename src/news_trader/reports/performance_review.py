from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path

from news_trader.signals.adaptive import AdaptiveState, save_adaptive_state
from news_trader.sources import market_data
from news_trader.storage import Store
from news_trader.trading.portfolio import mark_to_market


@dataclass
class ClosedLot:
    ticker: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    pnl: float


def run_performance_review(db_path: Path, starting_cash: float) -> dict:
    store = Store(db_path, starting_cash)
    closed_lots = _closed_lots(store)
    mark = mark_to_market(store)
    open_pnl = _open_pnl(store, mark.prices)
    realized_pnl = sum(lot.pnl for lot in closed_lots)
    total_pnl = (mark.equity - starting_cash) if starting_cash else realized_pnl + open_pnl
    win_rate = _win_rate(closed_lots)
    source_stats = _source_stats(store)
    classifier_stats = _classifier_stats(store)
    adaptive = _adaptive_decision(total_pnl, starting_cash, win_rate, len(closed_lots), mark.gross_exposure, mark.equity)
    save_adaptive_state(store, adaptive)

    review = {
        "cash": round(mark.cash, 4),
        "equity": round(mark.equity, 4),
        "starting_cash": round(starting_cash, 4),
        "realized_pnl": round(realized_pnl, 4),
        "open_pnl": round(open_pnl, 4),
        "total_pnl": round(total_pnl, 4),
        "total_return": round((mark.equity / starting_cash) - 1.0, 6) if starting_cash else 0.0,
        "closed_trades": len(closed_lots),
        "win_rate": win_rate,
        "source_stats": source_stats,
        "classifier_stats": classifier_stats,
        "adaptive_state": {
            "confidence_adjustment": adaptive.confidence_adjustment,
            "position_size_multiplier": adaptive.position_size_multiplier,
            "max_gross_exposure_multiplier": adaptive.max_gross_exposure_multiplier,
            "reason": adaptive.reason,
        },
    }
    store.insert_performance_review(review)
    _print_review(review)
    store.close()
    return review


def _closed_lots(store: Store) -> list[ClosedLot]:
    lots: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    closed: list[ClosedLot] = []
    rows = store.conn.execute("select * from trades order by id").fetchall()
    for row in rows:
        ticker = row["ticker"]
        action = row["action"]
        qty = abs(float(row["quantity"]))
        price = float(row["price"])
        if action == "buy":
            lots[ticker].append(("long", qty, price))
        elif action == "short":
            lots[ticker].append(("short", qty, price))
        elif action == "sell":
            closed.extend(_close_lots(lots[ticker], "long", qty, price, ticker))
        elif action == "cover":
            closed.extend(_close_lots(lots[ticker], "short", qty, price, ticker))
    return closed


def _close_lots(
    lots: list[tuple[str, float, float]],
    side: str,
    quantity: float,
    exit_price: float,
    ticker: str,
) -> list[ClosedLot]:
    closed: list[ClosedLot] = []
    remaining = quantity
    kept: list[tuple[str, float, float]] = []
    for lot_side, lot_qty, entry_price in lots:
        if remaining <= 0 or lot_side != side:
            kept.append((lot_side, lot_qty, entry_price))
            continue
        close_qty = min(remaining, lot_qty)
        pnl = (exit_price - entry_price) * close_qty if side == "long" else (entry_price - exit_price) * close_qty
        closed.append(ClosedLot(ticker, side, close_qty, entry_price, exit_price, pnl))
        remaining -= close_qty
        if lot_qty > close_qty:
            kept.append((lot_side, lot_qty - close_qty, entry_price))
    lots[:] = kept
    return closed


def _open_pnl(store: Store, prices: dict[str, float]) -> float:
    total = 0.0
    for row in store.all_positions():
        ticker = row["ticker"]
        qty = float(row["quantity"])
        avg = float(row["avg_price"])
        price = prices.get(ticker) or market_data.latest_price(ticker) or avg
        total += (price - avg) * qty
    return total


def _win_rate(closed_lots: list[ClosedLot]) -> float | None:
    if not closed_lots:
        return None
    wins = sum(1 for lot in closed_lots if lot.pnl > 0)
    return round(wins / len(closed_lots), 4)


def _source_stats(store: Store) -> dict:
    rows = store.conn.execute(
        """
        select e.source, count(*) as events, sum(case when d.id is null then 0 else 1 end) as decisions
        from events e
        left join decisions d on d.event_id = e.id
        group by e.source
        order by events desc
        """
    ).fetchall()
    return {row["source"]: {"events": row["events"], "decisions": row["decisions"]} for row in rows}


def _classifier_stats(store: Store) -> dict:
    rows = store.conn.execute("select decision_json from decisions order by id desc limit 500").fetchall()
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "buy": 0, "sell": 0, "short": 0, "cover": 0, "hold": 0})
    for row in rows:
        try:
            data = json.loads(row["decision_json"])
        except json.JSONDecodeError:
            continue
        classifier = data.get("classifier") or data.get("model") or "unknown"
        signal = data.get("signal", {})
        action = signal.get("action", "hold")
        buckets[classifier]["total"] += 1
        buckets[classifier][action if action in buckets[classifier] else "hold"] += 1
    return dict(buckets)


def _adaptive_decision(
    total_pnl: float,
    starting_cash: float,
    win_rate: float | None,
    closed_trades: int,
    gross_exposure: float,
    equity: float,
) -> AdaptiveState:
    total_return = (total_pnl / starting_cash) if starting_cash else 0.0
    exposure_ratio = (gross_exposure / equity) if equity > 0 else 0.0
    if total_return <= -0.05 or (closed_trades >= 5 and win_rate is not None and win_rate < 0.35):
        return AdaptiveState(
            confidence_adjustment=-0.08,
            position_size_multiplier=0.50,
            max_gross_exposure_multiplier=0.60,
            reason="Review detected weak performance; tightened confidence, size, and exposure.",
        )
    if total_return <= -0.02 or exposure_ratio > 1.0:
        return AdaptiveState(
            confidence_adjustment=-0.04,
            position_size_multiplier=0.70,
            max_gross_exposure_multiplier=0.80,
            reason="Review detected drawdown or high exposure; moderately tightened risk.",
        )
    if closed_trades >= 5 and win_rate is not None and win_rate >= 0.60 and total_return > 0.02:
        return AdaptiveState(
            confidence_adjustment=0.02,
            position_size_multiplier=1.10,
            max_gross_exposure_multiplier=1.00,
            reason="Review detected positive realized performance; cautiously allowing normal-to-slightly-larger sizing.",
        )
    return AdaptiveState(
        confidence_adjustment=0.0,
        position_size_multiplier=1.0,
        max_gross_exposure_multiplier=1.0,
        reason="Insufficient or neutral performance evidence; keeping baseline strategy settings.",
    )


def _print_review(review: dict) -> None:
    print("Performance review")
    print(f"Equity: ${review['equity']:.2f}")
    print(f"Total P/L: ${review['total_pnl']:.2f} ({review['total_return']:.2%})")
    print(f"Realized P/L: ${review['realized_pnl']:.2f}")
    print(f"Open P/L: ${review['open_pnl']:.2f}")
    print(f"Closed trades: {review['closed_trades']}")
    print(f"Win rate: {review['win_rate'] if review['win_rate'] is not None else 'N/A'}")
    adaptive = review["adaptive_state"]
    print("Adaptive state:")
    print(f"  confidence adjustment: {adaptive['confidence_adjustment']:+.2f}")
    print(f"  position size multiplier: {adaptive['position_size_multiplier']:.2f}")
    print(f"  gross exposure multiplier: {adaptive['max_gross_exposure_multiplier']:.2f}")
    print(f"  reason: {adaptive['reason']}")
