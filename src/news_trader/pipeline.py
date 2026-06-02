from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from news_trader.config import AppConfig
from news_trader.llm.client import DecisionClient
from news_trader.market_hours import is_us_market_open
from news_trader.signals.adaptive import load_adaptive_state
from news_trader.signals.derisk import apply_drawdown_derisk
from news_trader.signals.risk import RiskEngine
from news_trader.signals.scoring import build_signal
from news_trader.sources import event_calendar, market_data, sec_edgar, yahoo_rss
from news_trader.sources.event_calendar import UpcomingEvent
from news_trader.sources.registry import SourceSpec, load_source_registry
from news_trader.storage import Store, SourceItem
from news_trader.storage import utc_now
from news_trader.trading.paper_broker import LocalPaperBroker
from news_trader.trading.portfolio import mark_to_market


def collect_items(
    config: AppConfig,
    store: Store,
    run_id: str,
    source_registry: list[SourceSpec],
) -> tuple[list[SourceItem], dict[str, list[UpcomingEvent]]]:
    cache_dir = config.root / "data" / "cache"
    items: list[SourceItem] = []
    upcoming_by_ticker: dict[str, list[UpcomingEvent]] = {ticker.symbol: [] for ticker in config.tickers}
    symbols = [ticker.symbol for ticker in config.tickers]
    for source in source_registry:
        started_at = utc_now()
        before = len(items)
        status = "ok"
        error = None
        try:
            if source.id == "event_calendar" and config.sources.event_calendar_enabled:
                upcoming = event_calendar.fetch_upcoming_events(config.root, symbols, config.sources.calendar_lookahead_days)
                for event in upcoming:
                    upcoming_by_ticker.setdefault(event.symbol, []).append(event)
                    items.append(event_calendar.as_source_item(event))
            elif source.id == "sec_edgar" and config.sources.sec_enabled:
                for ticker in config.tickers:
                    items.extend(
                        sec_edgar.fetch_recent_filings(ticker.symbol, cache_dir, config.sources.max_items_per_source)
                    )
            elif source.id == "yahoo_rss" and config.sources.yahoo_rss_enabled:
                for ticker in config.tickers:
                    items.extend(yahoo_rss.fetch_news(ticker.symbol, config.sources.max_items_per_source))
            elif source.id == "market_data":
                # Market data is collected in _feature_cache and logged there as a source run.
                continue
            else:
                status = "disabled"
        except Exception as exc:
            status = "error"
            error = str(exc)
            print(f"{source.id} fetch failed: {exc}")
        completed_at = utc_now()
        store.insert_source_run(run_id, source.id, status, len(items) - before, started_at, completed_at, error)
    return items, upcoming_by_ticker


def run_once(config: AppConfig, db_path: Path) -> None:
    store = Store(db_path, config.trading.starting_cash_usd)
    run_id = str(uuid4())
    source_registry = load_source_registry(config.root)
    decision_client = DecisionClient(config.root, source_registry)
    adaptive = load_adaptive_state(store)
    broker = LocalPaperBroker(
        store,
        allow_fractional=config.trading.allow_fractional,
    )
    risk = RiskEngine(store, config.trading, adaptive)
    feature_cache = _feature_cache(config, store, run_id)
    _update_benchmark_state(store)
    price_overrides = {
        symbol: features.latest_price for symbol, features in feature_cache.items() if features.latest_price is not None
    }
    mark = mark_to_market(store, price_overrides)
    risk.update_peak_equity(mark.equity)
    store.insert_portfolio_snapshot(mark.cash, mark.equity, mark.gross_exposure, mark.prices)
    market_open = is_us_market_open(market_timezone=config.schedule.market_timezone)
    if config.schedule.trade_market_hours_only and not market_open:
        print("US market is closed. Scanning and logging only; no trades will be placed.")
    else:
        derisk = apply_drawdown_derisk(store, broker, config.trading, mark)
        if derisk.triggered:
            print(f"De-risk check: {derisk.reason}")
            mark = derisk.mark

    new_events = 0
    submitted_orders = 0
    items, upcoming_by_ticker = collect_items(config, store, run_id, source_registry)
    for item in items:
        event_id = store.insert_event(item)
        if event_id is None:
            continue
        new_events += 1
        classification = decision_client.decide(item)
        position = store.position(item.ticker)
        existing_quantity = float(position["quantity"]) if position else 0.0
        features = feature_cache.get(item.ticker) or market_data.market_features(item.ticker)
        signal = build_signal(
            item,
            classification,
            features,
            config.trading,
            mark.equity,
            existing_quantity,
            upcoming_by_ticker.get(item.ticker, []),
            adaptive,
        )
        decision = {
            "classification": classification,
            "signal": {
                "ticker": signal.ticker,
                "action": signal.action,
                "confidence": signal.confidence,
                "target_notional": signal.target_notional,
                "reason": signal.reason,
                "components": signal.components,
            },
        }
        store.insert_decision(event_id, decision_client.model, "v2", decision)
        if config.schedule.trade_market_hours_only and not market_open:
            continue
        price = features.latest_price
        risk_decision = risk.evaluate(signal, price, mark.equity, mark.gross_exposure)
        if not risk_decision.allowed:
            print(f"Skipped {item.ticker}: {risk_decision.reason}")
            continue
        result = broker.submit(
            item.ticker,
            signal.action,
            price,
            risk_decision.notional,
            signal.reason,
        )
        print(result.reason)
        if result.submitted:
            submitted_orders += 1
            mark = mark_to_market(store, price_overrides)
            risk.update_peak_equity(mark.equity)
    final_mark = mark_to_market(store, price_overrides)
    store.insert_portfolio_snapshot(final_mark.cash, final_mark.equity, final_mark.gross_exposure, final_mark.prices)
    print(
        "Run complete. "
        f"Run id: {run_id}. "
        f"New events: {new_events}. Paper orders: {submitted_orders}. "
        f"Cash: ${final_mark.cash:.2f}. Equity: ${final_mark.equity:.2f}. "
        f"Gross exposure: ${final_mark.gross_exposure:.2f}."
    )


def _feature_cache(config: AppConfig, store: Store, run_id: str):
    started_at = utc_now()
    features = {}
    errors: list[str] = []
    for ticker in config.tickers:
        try:
            features[ticker.symbol] = market_data.market_features(ticker.symbol)
        except Exception as exc:
            message = f"{ticker.symbol}: {exc}"
            errors.append(message)
            print(f"Market feature fetch failed for {message}")
    status = "error" if errors and not features else "partial" if errors else "ok"
    store.insert_source_run(
        run_id,
        "market_data",
        status,
        len(features),
        started_at,
        utc_now(),
        "; ".join(errors) if errors else None,
    )
    return features


def _update_benchmark_state(store: Store) -> None:
    for symbol in ("SPY", "QQQ"):
        try:
            price = market_data.latest_price(symbol)
        except Exception:
            price = None
        if price is None:
            continue
        if store.get_state(f"benchmark_start_{symbol}") is None:
            store.set_state(f"benchmark_start_{symbol}", f"{price:.6f}")
        store.set_state(f"benchmark_last_{symbol}", f"{price:.6f}")
