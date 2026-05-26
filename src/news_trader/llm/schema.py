from __future__ import annotations


EVENT_TYPES = {
    "filing",
    "earnings",
    "guidance",
    "legal",
    "product",
    "analyst",
    "capital_return",
    "m_and_a",
    "macro",
    "other",
}

SOURCE_RELIABILITY = {"high", "medium", "low"}
DIRECTIONAL_BIAS = {"bullish", "bearish", "neutral", "unclear"}

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "ticker",
        "event_type",
        "summary",
        "source_reliability",
        "market_relevance",
        "directional_bias",
        "confidence",
        "requires_human_review",
        "evidence",
    ],
    "properties": {
        "ticker": {"type": "string"},
        "event_type": {"type": "string", "enum": sorted(EVENT_TYPES)},
        "summary": {"type": "string", "maxLength": 500},
        "source_reliability": {"type": "string", "enum": sorted(SOURCE_RELIABILITY)},
        "market_relevance": {"type": "integer", "minimum": 0, "maximum": 100},
        "directional_bias": {"type": "string", "enum": sorted(DIRECTIONAL_BIAS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "requires_human_review": {"type": "boolean"},
        "evidence": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 220},
        },
    },
}


def normalize_classification(raw: dict, ticker: str, source: str) -> dict:
    event_type = _enum(raw.get("event_type"), EVENT_TYPES, "other")
    reliability = _enum(raw.get("source_reliability"), SOURCE_RELIABILITY, _default_reliability(source))
    bias = _enum(raw.get("directional_bias"), DIRECTIONAL_BIAS, "unclear")
    return {
        "ticker": str(raw.get("ticker") or ticker).upper(),
        "event_type": event_type,
        "summary": _text(raw.get("summary"), "No summary supplied.", 500),
        "source_reliability": reliability,
        "market_relevance": int(_bounded(_number(raw.get("market_relevance"), 0), 0, 100)),
        "directional_bias": bias,
        "confidence": _bounded(_number(raw.get("confidence"), 0), 0, 1),
        "requires_human_review": bool(raw.get("requires_human_review", bias == "unclear")),
        "evidence": _evidence(raw.get("evidence")),
    }


def _enum(value, allowed: set[str], fallback: str) -> str:
    value_str = str(value or "").lower()
    return value_str if value_str in allowed else fallback


def _text(value, fallback: str, max_len: int) -> str:
    text = str(value or fallback).strip()
    return text[:max_len]


def _number(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _evidence(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:220] for item in value[:5]]


def _default_reliability(source: str) -> str:
    if source in {"sec_edgar", "company_ir", "manual_calendar"}:
        return "high"
    if source in {"event_calendar", "yahoo_rss", "market_data"}:
        return "medium"
    return "low"
