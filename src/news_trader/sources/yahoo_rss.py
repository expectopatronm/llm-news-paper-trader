from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from urllib.parse import quote

from news_trader.sources.http import fetch_text
from news_trader.storage import SourceItem


def fetch_news(symbol: str, limit: int = 8) -> list[SourceItem]:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote(symbol)}&region=US&lang=en-US"
    xml_text = fetch_text(url, {"User-Agent": "llm-news-paper-trader/0.1"})
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []
    items: list[SourceItem] = []
    for entry in channel.findall("item"):
        title = (entry.findtext("title") or "").strip()
        link = (entry.findtext("link") or "").strip()
        pub_date = (entry.findtext("pubDate") or "").strip()
        description = (entry.findtext("description") or "").strip()
        if not title or not link:
            continue
        source_id = hashlib.sha256(link.encode("utf-8")).hexdigest()
        items.append(
            SourceItem(
                ticker=symbol,
                source="yahoo_rss",
                source_id=source_id,
                title=title,
                url=link,
                published_at=pub_date,
                raw_text=f"{title}\n{description}",
            )
        )
        if len(items) >= limit:
            break
    return items

