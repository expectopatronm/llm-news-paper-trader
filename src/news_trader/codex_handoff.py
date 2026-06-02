from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from uuid import uuid4

from news_trader.config import AppConfig
from news_trader.llm.schema import CLASSIFICATION_SCHEMA, normalize_classification
from news_trader.market_hours import is_us_market_open
from news_trader.pipeline import _feature_cache, _update_benchmark_state, collect_items
from news_trader.reports.performance_review import run_performance_review
from news_trader.signals.adaptive import load_adaptive_state
from news_trader.signals.derisk import apply_drawdown_derisk
from news_trader.signals.risk import RiskEngine
from news_trader.signals.scoring import build_signal
from news_trader.sources.event_calendar import UpcomingEvent
from news_trader.sources.market_data import MarketFeatures
from news_trader.sources.registry import load_source_registry, source_manifest_for_prompt
from news_trader.storage import SourceItem, Store
from news_trader.trading.paper_broker import LocalPaperBroker
from news_trader.trading.portfolio import mark_to_market


PENDING_PATH = Path("data/codex_pending_events.json")
CLASSIFICATIONS_PATH = Path("data/codex_classifications.json")


def collect_for_codex(config: AppConfig, db_path: Path, pending_path: Path | None = None) -> Path:
    pending_path = _resolve(config.root, pending_path or PENDING_PATH)
    store = Store(db_path, config.trading.starting_cash_usd)
    adaptive = load_adaptive_state(store)
    run_id = str(uuid4())
    source_registry = load_source_registry(config.root)
    feature_cache = _feature_cache(config, store, run_id)
    _update_benchmark_state(store)
    price_overrides = {
        symbol: features.latest_price for symbol, features in feature_cache.items() if features.latest_price is not None
    }
    mark = mark_to_market(store, price_overrides)
    RiskEngine(store, config.trading, adaptive).update_peak_equity(mark.equity)
    store.insert_portfolio_snapshot(mark.cash, mark.equity, mark.gross_exposure, mark.prices)

    items, upcoming_by_ticker = collect_items(config, store, run_id, source_registry)
    pending_events = []
    for item in items:
        event_id = store.insert_event(item)
        if event_id is None:
            continue
        position = store.position(item.ticker)
        pending_events.append(
            {
                "event_id": event_id,
                "source_item": asdict(item),
                "market_features": asdict(feature_cache[item.ticker]) if item.ticker in feature_cache else None,
                "existing_quantity": float(position["quantity"]) if position else 0.0,
                "upcoming_events": [_event_to_json(event) for event in upcoming_by_ticker.get(item.ticker, [])],
            }
        )

    payload = {
        "run_id": run_id,
        "mode": "codex_classification_required",
        "market_open": is_us_market_open(market_timezone=config.schedule.market_timezone),
        "trade_market_hours_only": config.schedule.trade_market_hours_only,
        "source_registry": source_manifest_for_prompt(source_registry),
        "classification_schema": CLASSIFICATION_SCHEMA,
        "instructions": [
            "Classify every pending event. Do not omit events.",
            "Use only source_item text/title/url/source and supplied context.",
            "Do not classify negative operating evidence as bullish unless the same source item gives a clear offsetting positive surprise.",
            "Treat generic listicles, promotional language, stale news, or ambiguous company references as low-confidence and likely human-review items.",
            "Return classifications in data/codex_classifications.json.",
            "Do not include trading actions, sizes, or broker instructions.",
        ],
        "adaptive_state": {
            "confidence_adjustment": adaptive.confidence_adjustment,
            "position_size_multiplier": adaptive.position_size_multiplier,
            "max_gross_exposure_multiplier": adaptive.max_gross_exposure_multiplier,
            "reason": adaptive.reason,
        },
        "pending_events": pending_events,
    }
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Codex pending file written: {pending_path}")
    print(f"Run id: {run_id}. Pending events: {len(pending_events)}.")
    if not pending_events:
        print("No new events need Codex classification.")
    store.close()
    return pending_path


def execute_codex_classifications(
    config: AppConfig,
    db_path: Path,
    pending_path: Path | None = None,
    classifications_path: Path | None = None,
) -> None:
    pending_path = _resolve(config.root, pending_path or PENDING_PATH)
    classifications_path = _resolve(config.root, classifications_path or CLASSIFICATIONS_PATH)
    if not pending_path.exists():
        raise FileNotFoundError(f"Missing pending file: {pending_path}")
    if not classifications_path.exists():
        raise FileNotFoundError(f"Missing classifications file: {classifications_path}")

    pending = _read_json(pending_path)
    raw_classifications = _read_json(classifications_path)
    by_event_id = _classification_map(raw_classifications)
    store = Store(db_path, config.trading.starting_cash_usd)
    broker = LocalPaperBroker(store, allow_fractional=config.trading.allow_fractional)
    adaptive = load_adaptive_state(store)
    risk = RiskEngine(store, config.trading, adaptive)
    market_open = bool(pending.get("market_open"))
    if config.schedule.trade_market_hours_only and not market_open:
        print("US market is closed. Classifications will be stored; no trades will be placed.")

    mark = mark_to_market(store)
    risk.update_peak_equity(mark.equity)
    if not (config.schedule.trade_market_hours_only and not market_open):
        derisk = apply_drawdown_derisk(store, broker, config.trading, mark)
        if derisk.triggered:
            print(f"De-risk check: {derisk.reason}")
            mark = derisk.mark
    submitted_orders = 0
    classified = 0
    for pending_event in pending.get("pending_events", []):
        event_id = int(pending_event["event_id"])
        raw = by_event_id.get(event_id)
        if raw is None:
            raise ValueError(f"Missing classification for event_id {event_id}")
        row = store.event_by_id(event_id)
        if row is None:
            raise ValueError(f"Event {event_id} no longer exists in SQLite")
        item = SourceItem(
            ticker=row["ticker"],
            source=row["source"],
            source_id=row["source_id"],
            title=row["title"],
            url=row["url"],
            published_at=row["published_at"] or "",
            raw_text=row["raw_text"],
        )
        classification = normalize_classification(raw, item.ticker, item.source)
        features = _market_features_from_json(pending_event.get("market_features"))
        upcoming = [_event_from_json(event) for event in pending_event.get("upcoming_events", [])]
        signal = build_signal(
            item,
            classification,
            features,
            config.trading,
            mark.equity,
            float(pending_event.get("existing_quantity", 0.0)),
            upcoming,
            adaptive,
        )
        decision = {
            "classifier": "codex",
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
        store.insert_decision(event_id, "codex", "codex-v1", decision)
        classified += 1
        if config.schedule.trade_market_hours_only and not market_open:
            continue
        risk_decision = risk.evaluate(signal, features.latest_price, mark.equity, mark.gross_exposure)
        if not risk_decision.allowed:
            print(f"Skipped {item.ticker}: {risk_decision.reason}")
            continue
        result = broker.submit(item.ticker, signal.action, features.latest_price, risk_decision.notional, signal.reason)
        print(result.reason)
        if result.submitted:
            submitted_orders += 1
            mark = mark_to_market(store, {item.ticker: features.latest_price})
            risk.update_peak_equity(mark.equity)

    final_mark = mark_to_market(store)
    store.insert_portfolio_snapshot(final_mark.cash, final_mark.equity, final_mark.gross_exposure, final_mark.prices)
    print(
        "Codex execution complete. "
        f"Run id: {pending.get('run_id')}. "
        f"Classified events: {classified}. Paper orders: {submitted_orders}. "
        f"Cash: ${final_mark.cash:.2f}. Equity: ${final_mark.equity:.2f}. "
        f"Gross exposure: ${final_mark.gross_exposure:.2f}."
    )
    store.close()
    run_performance_review(db_path, config.trading.starting_cash_usd)


def _classification_map(raw_classifications) -> dict[int, dict]:
    if isinstance(raw_classifications, dict):
        rows = raw_classifications.get("classifications", [])
    else:
        rows = raw_classifications
    mapping: dict[int, dict] = {}
    for row in rows:
        event_id = int(row["event_id"])
        classification = row.get("classification", row)
        mapping[event_id] = classification
    return mapping


def _market_features_from_json(raw: dict | None) -> MarketFeatures:
    if not raw:
        return MarketFeatures("", None, None, None, None, None, None, None, None)
    return MarketFeatures(**raw)


def _event_to_json(event: UpcomingEvent) -> dict:
    payload = asdict(event)
    payload["date"] = event.date.isoformat()
    return payload


def _event_from_json(raw: dict) -> UpcomingEvent:
    from datetime import date

    return UpcomingEvent(
        symbol=raw["symbol"],
        event_type=raw["event_type"],
        date=date.fromisoformat(raw["date"]),
        description=raw["description"],
        source_url=raw["source_url"],
        source=raw["source"],
    )


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _read_json(path: Path):
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return json.loads(raw.decode("utf-8", errors="replace"))
