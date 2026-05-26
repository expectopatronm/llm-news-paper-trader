from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class SourceSpec:
    id: str
    enabled: bool
    priority: int
    cadence: str
    scope: str
    tool: str
    purpose: str
    reliability: str


def load_source_registry(root: Path) -> list[SourceSpec]:
    path = root / "config" / "source_registry.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sources = [SourceSpec(**item) for item in data.get("source", [])]
    return sorted((source for source in sources if source.enabled), key=lambda source: source.priority)


def source_manifest_for_prompt(sources: list[SourceSpec]) -> list[dict[str, str | int]]:
    return [
        {
            "id": source.id,
            "priority": source.priority,
            "scope": source.scope,
            "purpose": source.purpose,
            "reliability": source.reliability,
        }
        for source in sources
    ]
