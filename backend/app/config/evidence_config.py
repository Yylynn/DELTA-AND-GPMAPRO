from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceConfig:
    weights: dict[str, float]
    active_signal_bars: int = 3
    recent_signal_bars: int = 10
    dominance_margin: float = 0.18
    mixed_min_score: float = 0.28
    minimum_score: float = 0.12
    stale_confidence_multiplier: float = 0.70
    very_stale_confidence_multiplier: float = 0.35
    unknown_confidence_multiplier: float = 0.25


EVIDENCE_CONFIG = EvidenceConfig(weights={"DELTA": 1.0, "GPMAPRO": 1.0, "VOLUME": 0.8, "BACKTEST": 1.0, "DATA": 0.0, "NEWS": 0.0})
