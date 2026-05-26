from __future__ import annotations

import json
import os
from pathlib import Path

from news_trader.llm.schema import CLASSIFICATION_SCHEMA, normalize_classification
from news_trader.sources.registry import SourceSpec, source_manifest_for_prompt


def _load_prompt(root: Path, name: str) -> str:
    return (root / "prompts" / name).read_text(encoding="utf-8")


class DecisionClient:
    def __init__(self, root: Path, source_registry: list[SourceSpec] | None = None):
        self.root = root
        self.source_registry = source_registry or []
        self.model = os.getenv("OPENAI_MODEL", "rule-based")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.allow_rule_fallback = os.getenv("ALLOW_RULE_FALLBACK", "").lower() in {"1", "true", "yes"}

    def decide(self, item) -> dict:
        if not self.api_key:
            if self.allow_rule_fallback:
                return normalize_classification(self._rule_based_classification(item), item.ticker, item.source)
            raise RuntimeError(
                "No OPENAI_API_KEY is set and rule fallback is disabled. "
                "Use codex-collect/codex-execute so Codex classifies pending events."
            )
        try:
            return normalize_classification(self._openai_classification(item), item.ticker, item.source)
        except Exception as exc:
            if not self.allow_rule_fallback:
                raise
            decision = self._rule_based_classification(item)
            decision["llm_error"] = str(exc)
            return normalize_classification(decision, item.ticker, item.source)

    def _openai_classification(self, item) -> dict:
        from openai import OpenAI

        extraction_prompt = _load_prompt(self.root, "event_extraction.md")
        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": extraction_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "deterministic_source_registry": source_manifest_for_prompt(self.source_registry),
                            "output_schema": CLASSIFICATION_SCHEMA,
                            "ticker": item.ticker,
                            "source": item.source,
                            "title": item.title,
                            "published_at": item.published_at,
                            "url": item.url,
                            "text": item.raw_text[:5000],
                        }
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        decision = json.loads(content)
        decision.setdefault("ticker", item.ticker)
        decision.setdefault("event_type", "other")
        decision.setdefault("directional_bias", "unclear")
        decision.setdefault("confidence", 0)
        return decision

    def _rule_based_classification(self, item) -> dict:
        text = f"{item.title}\n{item.raw_text}".lower()
        bearish = ["miss", "downgrade", "investigation", "lawsuit", "subpoena", "cuts guidance", "resigns"]
        bullish = ["beats", "raises guidance", "upgrade", "record revenue", "buyback", "dividend increase"]
        event_type = self._event_type(item, text)
        if any(word in text for word in bearish):
            return {
                "ticker": item.ticker,
                "event_type": event_type,
                "source_reliability": self._source_reliability(item.source),
                "market_relevance": 72,
                "directional_bias": "bearish",
                "confidence": 0.72,
                "summary": f"Rule-based bearish event from {item.source}: {item.title}",
            }
        if any(word in text for word in bullish):
            return {
                "ticker": item.ticker,
                "event_type": event_type,
                "source_reliability": self._source_reliability(item.source),
                "market_relevance": 72,
                "directional_bias": "bullish",
                "confidence": 0.72,
                "summary": f"Rule-based bullish event from {item.source}: {item.title}",
            }
        return {
            "ticker": item.ticker,
            "event_type": event_type,
            "source_reliability": self._source_reliability(item.source),
            "market_relevance": 45 if event_type != "other" else 25,
            "directional_bias": "unclear",
            "confidence": 0.5,
            "summary": f"No strong directional signal from {item.source}: {item.title}",
        }

    def _event_type(self, item, text: str) -> str:
        if "earnings" in text or "eps" in text or "quarterly results" in text:
            return "earnings"
        if "guidance" in text or "outlook" in text:
            return "guidance"
        if any(word in text for word in ["lawsuit", "investigation", "probe", "antitrust", "subpoena"]):
            return "legal"
        if any(word in text for word in ["upgrade", "downgrade", "price target", "analyst"]):
            return "analyst"
        if any(word in text for word in ["buyback", "repurchase", "dividend"]):
            return "capital_return"
        if any(word in text for word in ["merger", "acquisition", "acquires", "takeover"]):
            return "m_and_a"
        if item.source == "sec_edgar":
            return "filing"
        return "other"

    def _source_reliability(self, source: str) -> str:
        if source in {"sec_edgar", "company_ir", "manual_calendar"}:
            return "high"
        if source in {"event_calendar", "yahoo_rss"}:
            return "medium"
        return "low"
