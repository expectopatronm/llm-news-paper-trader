from __future__ import annotations

import json
import os
from pathlib import Path

from news_trader.sources.http import fetch_text
from news_trader.storage import SourceItem


def sec_headers() -> dict[str, str]:
    return {
        "User-Agent": os.getenv("SEC_USER_AGENT", "llm-news-paper-trader contact@example.com"),
        "Accept-Encoding": "identity",
    }


def _sec_symbol(symbol: str) -> str:
    return symbol.replace(".", "-").upper()


def load_cik_map(cache_dir: Path) -> dict[str, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "company_tickers.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        data = json.loads(fetch_text("https://www.sec.gov/files/company_tickers.json", sec_headers()))
        cache_path.write_text(json.dumps(data), encoding="utf-8")
    mapping: dict[str, str] = {}
    for item in data.values():
        mapping[item["ticker"].upper()] = str(item["cik_str"]).zfill(10)
    return mapping


def fetch_recent_filings(symbol: str, cache_dir: Path, limit: int = 8) -> list[SourceItem]:
    cik = load_cik_map(cache_dir).get(_sec_symbol(symbol))
    if not cik:
        return []
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = json.loads(fetch_text(url, sec_headers()))
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    items: list[SourceItem] = []
    interesting_forms = {"8-K", "10-Q", "10-K", "DEF 14A", "4", "S-1", "6-K"}
    for form, accession, filing_date, primary_doc in zip(forms, accessions, dates, primary_docs):
        if form not in interesting_forms:
            continue
        accession_clean = accession.replace("-", "")
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{primary_doc}"
        title = f"{symbol} {form} filed {filing_date}"
        items.append(
            SourceItem(
                ticker=symbol,
                source="sec_edgar",
                source_id=accession,
                title=title,
                url=filing_url,
                published_at=filing_date,
                raw_text=f"{title}. SEC accession {accession}.",
            )
        )
        if len(items) >= limit:
            break
    return items
