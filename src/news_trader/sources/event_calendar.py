from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import hashlib
import json
import tomllib

from news_trader.sources.http import fetch_text
from news_trader.storage import SourceItem


@dataclass(frozen=True)
class UpcomingEvent:
    symbol: str
    event_type: str
    date: date
    description: str
    source_url: str
    source: str


def fetch_upcoming_events(root: Path, symbols: list[str], lookahead_days: int) -> list[UpcomingEvent]:
    events = _load_manual_events(root, symbols, lookahead_days)
    try:
        events.extend(_fetch_nasdaq_calendar(symbols, lookahead_days))
    except Exception as exc:
        print(f"Nasdaq calendar fetch failed: {exc}")
    return _dedupe_events(events)


def as_source_item(event: UpcomingEvent) -> SourceItem:
    source_id = hashlib.sha256(
        f"{event.source}:{event.symbol}:{event.event_type}:{event.date.isoformat()}".encode("utf-8")
    ).hexdigest()
    return SourceItem(
        ticker=event.symbol,
        source=event.source,
        source_id=source_id,
        title=f"Upcoming {event.event_type} for {event.symbol} on {event.date.isoformat()}",
        url=event.source_url,
        published_at=event.date.isoformat(),
        raw_text=event.description,
    )


def _load_manual_events(root: Path, symbols: list[str], lookahead_days: int) -> list[UpcomingEvent]:
    path = root / "config" / "events.toml"
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    today = date.today()
    wanted = {symbol.upper() for symbol in symbols}
    events: list[UpcomingEvent] = []
    for raw in data.get("event", []):
        symbol = str(raw.get("symbol", "")).upper()
        event_date = _coerce_date(raw.get("date"))
        if not symbol or symbol not in wanted or event_date is None:
            continue
        days_until = (event_date - today).days
        if days_until < 0 or days_until > lookahead_days:
            continue
        events.append(
            UpcomingEvent(
                symbol=symbol,
                event_type=str(raw.get("event_type", "event")),
                date=event_date,
                description=str(raw.get("description", "")),
                source_url=str(raw.get("source_url", "")),
                source="manual_calendar",
            )
        )
    return events


def _fetch_nasdaq_calendar(symbols: list[str], lookahead_days: int) -> list[UpcomingEvent]:
    wanted = {symbol.upper() for symbol in symbols}
    today = date.today()
    events: list[UpcomingEvent] = []
    for offset in range(lookahead_days + 1):
        event_date = today + timedelta(days=offset)
        url = f"https://api.nasdaq.com/api/calendar/earnings?date={event_date.isoformat()}"
        text = fetch_text(url, {"User-Agent": "Mozilla/5.0 llm-news-paper-trader/0.1", "Accept": "application/json"})
        data = json.loads(text)
        rows = data.get("data", {}).get("rows") or []
        for row in rows:
            symbol = str(row.get("symbol", "")).upper()
            if symbol not in wanted:
                continue
            eps = row.get("epsForecast") or "N/A"
            quarter = row.get("fiscalQuarterEnding") or "N/A"
            time_hint = str(row.get("time") or "time-not-supplied").replace("time-", "").replace("-", " ")
            description = (
                f"Upcoming earnings event for {symbol}. "
                f"Fiscal quarter ending: {quarter}. Consensus EPS forecast: {eps}. "
                f"Release timing: {time_hint}."
            )
            events.append(
                UpcomingEvent(
                    symbol=symbol,
                    event_type="earnings",
                    date=event_date,
                    description=description,
                    source_url="https://www.nasdaq.com/market-activity/earnings",
                    source="event_calendar",
                )
            )
    return events


def _coerce_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def _dedupe_events(events: list[UpcomingEvent]) -> list[UpcomingEvent]:
    seen: set[tuple[str, str, date]] = set()
    unique: list[UpcomingEvent] = []
    for event in events:
        key = (event.symbol, event.event_type, event.date)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique
