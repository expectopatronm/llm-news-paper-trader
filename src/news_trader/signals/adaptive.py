from __future__ import annotations

from dataclasses import dataclass

from news_trader.storage import Store


@dataclass(frozen=True)
class AdaptiveState:
    confidence_adjustment: float
    position_size_multiplier: float
    max_gross_exposure_multiplier: float
    reason: str


def load_adaptive_state(store: Store) -> AdaptiveState:
    return AdaptiveState(
        confidence_adjustment=float(store.get_state("adaptive_confidence_adjustment") or 0.0),
        position_size_multiplier=float(store.get_state("adaptive_position_size_multiplier") or 1.0),
        max_gross_exposure_multiplier=float(store.get_state("adaptive_gross_exposure_multiplier") or 1.0),
        reason=store.get_state("adaptive_reason") or "No adaptive review yet.",
    )


def save_adaptive_state(store: Store, state: AdaptiveState) -> None:
    store.set_state("adaptive_confidence_adjustment", f"{state.confidence_adjustment:.6f}")
    store.set_state("adaptive_position_size_multiplier", f"{state.position_size_multiplier:.6f}")
    store.set_state("adaptive_gross_exposure_multiplier", f"{state.max_gross_exposure_multiplier:.6f}")
    store.set_state("adaptive_reason", state.reason)
