from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceItem:
    ticker: str
    source: str
    source_id: str
    title: str
    url: str
    published_at: str
    raw_text: str


class Store:
    def __init__(self, db_path: Path, starting_cash: float):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db(starting_cash)

    def _init_db(self, starting_cash: float) -> None:
        self.conn.executescript(
            """
            create table if not exists events (
              id integer primary key,
              ticker text not null,
              source text not null,
              source_id text not null,
              title text not null,
              url text not null,
              published_at text,
              raw_text text not null,
              created_at text not null,
              unique(source, source_id)
            );

            create table if not exists decisions (
              id integer primary key,
              event_id integer not null,
              model text not null,
              prompt_version text not null,
              decision_json text not null,
              created_at text not null,
              foreign key(event_id) references events(id)
            );

            create table if not exists trades (
              id integer primary key,
              ticker text not null,
              action text not null,
              quantity real not null,
              price real not null,
              notional real not null,
              reason text not null,
              created_at text not null
            );

            create table if not exists positions (
              ticker text primary key,
              quantity real not null,
              avg_price real not null
            );

            create table if not exists portfolio_state (
              key text primary key,
              value text not null
            );

            create table if not exists portfolio_snapshots (
              id integer primary key,
              cash real not null,
              equity real not null,
              gross_exposure real not null,
              prices_json text not null,
              created_at text not null
            );

            create table if not exists source_runs (
              id integer primary key,
              run_id text not null,
              source_id text not null,
              status text not null,
              items_seen integer not null,
              error text,
              started_at text not null,
              completed_at text not null
            );

            create table if not exists performance_reviews (
              id integer primary key,
              review_json text not null,
              created_at text not null
            );
            """
        )
        if self.get_state("cash_usd") is None:
            self.set_state("cash_usd", str(starting_cash))
            self.set_state("starting_cash_usd", str(starting_cash))
        self.conn.commit()

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("select value from portfolio_state where key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "insert into portfolio_state(key, value) values(?, ?) on conflict(key) do update set value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def insert_event(self, item: SourceItem) -> int | None:
        cur = self.conn.execute(
            """
            insert or ignore into events(ticker, source, source_id, title, url, published_at, raw_text, created_at)
            values(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item.ticker, item.source, item.source_id, item.title, item.url, item.published_at, item.raw_text, utc_now()),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        return int(cur.lastrowid)

    def event_by_id(self, event_id: int) -> sqlite3.Row | None:
        return self.conn.execute("select * from events where id = ?", (event_id,)).fetchone()

    def insert_decision(self, event_id: int, model: str, prompt_version: str, decision: dict) -> None:
        self.conn.execute(
            "insert into decisions(event_id, model, prompt_version, decision_json, created_at) values(?, ?, ?, ?, ?)",
            (event_id, model, prompt_version, json.dumps(decision, sort_keys=True), utc_now()),
        )
        self.conn.commit()

    def cash(self) -> float:
        return float(self.get_state("cash_usd") or 0)

    def set_cash(self, cash: float) -> None:
        self.set_state("cash_usd", f"{cash:.6f}")

    def position(self, ticker: str) -> sqlite3.Row | None:
        return self.conn.execute("select * from positions where ticker = ?", (ticker,)).fetchone()

    def all_positions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("select * from positions order by ticker"))

    def upsert_position(self, ticker: str, quantity: float, avg_price: float) -> None:
        if abs(quantity) < 1e-9:
            self.conn.execute("delete from positions where ticker = ?", (ticker,))
        else:
            self.conn.execute(
                "insert into positions(ticker, quantity, avg_price) values(?, ?, ?) "
                "on conflict(ticker) do update set quantity = excluded.quantity, avg_price = excluded.avg_price",
                (ticker, quantity, avg_price),
            )
        self.conn.commit()

    def insert_trade(self, ticker: str, action: str, quantity: float, price: float, reason: str) -> None:
        self.conn.execute(
            "insert into trades(ticker, action, quantity, price, notional, reason, created_at) values(?, ?, ?, ?, ?, ?, ?)",
            (ticker, action, quantity, price, abs(quantity * price), reason, utc_now()),
        )
        self.conn.commit()

    def insert_portfolio_snapshot(self, cash: float, equity: float, gross_exposure: float, prices: dict[str, float]) -> None:
        self.conn.execute(
            "insert into portfolio_snapshots(cash, equity, gross_exposure, prices_json, created_at) values(?, ?, ?, ?, ?)",
            (cash, equity, gross_exposure, json.dumps(prices, sort_keys=True), utc_now()),
        )
        self.conn.commit()

    def insert_source_run(
        self,
        run_id: str,
        source_id: str,
        status: str,
        items_seen: int,
        started_at: str,
        completed_at: str,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            insert into source_runs(run_id, source_id, status, items_seen, error, started_at, completed_at)
            values(?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, source_id, status, items_seen, error, started_at, completed_at),
        )
        self.conn.commit()

    def insert_performance_review(self, review: dict) -> None:
        self.conn.execute(
            "insert into performance_reviews(review_json, created_at) values(?, ?)",
            (json.dumps(review, sort_keys=True), utc_now()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
