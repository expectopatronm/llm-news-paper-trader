from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Ticker:
    symbol: str
    name: str


@dataclass(frozen=True)
class TradingConfig:
    starting_cash_usd: float
    base_position_pct: float
    max_position_pct: float
    max_short_position_pct: float
    max_gross_exposure_pct: float
    max_new_trades_per_day: int
    min_confidence: float
    max_drawdown_pct: float
    allow_shorts: bool
    allow_fractional: bool
    min_notional_usd: float
    paper_broker: str
    pead_follow_through_weight: float
    priced_in_penalty_weight: float
    buy_dip_enabled: bool
    buy_dip_min_drop_1d: float
    buy_dip_min_relative_drop_spy: float
    buy_dip_min_relative_drop_qqq_5d: float
    buy_dip_volume_ratio_min: float
    buy_dip_confidence_boost: float
    buy_dip_position_multiplier: float
    derisk_enabled: bool
    derisk_drawdown_pct: float
    derisk_target_gross_exposure_pct: float
    derisk_step_exposure_pct: float
    derisk_min_position_loss_pct: float


@dataclass(frozen=True)
class ScheduleConfig:
    interval_minutes: int
    timezone: str
    trade_market_hours_only: bool
    scan_outside_market_hours: bool
    market_timezone: str


@dataclass(frozen=True)
class SourcesConfig:
    sec_enabled: bool
    yahoo_rss_enabled: bool
    event_calendar_enabled: bool
    max_items_per_source: int
    calendar_lookahead_days: int


@dataclass(frozen=True)
class AppConfig:
    tickers: list[Ticker]
    trading: TradingConfig
    schedule: ScheduleConfig
    sources: SourcesConfig
    root: Path = ROOT


def _read_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(root: Path = ROOT) -> AppConfig:
    config_dir = root / "config"
    tickers_raw = _read_toml(config_dir / "tickers.toml")["ticker"]
    trading_raw = _read_toml(config_dir / "trading.toml")
    schedule_raw = _read_toml(config_dir / "schedule.toml")
    sources_raw = _read_toml(config_dir / "sources.toml")

    return AppConfig(
        tickers=[Ticker(**item) for item in tickers_raw],
        trading=TradingConfig(**trading_raw),
        schedule=ScheduleConfig(**schedule_raw),
        sources=SourcesConfig(**sources_raw),
        root=root,
    )
