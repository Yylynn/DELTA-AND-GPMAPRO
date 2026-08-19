from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionConfig:
    buy_min_confidence: float = .60
    buy_min_bullish_score: float = .55
    buy_min_score_spread: float = .20
    buy_min_confirmations: int = 3
    flexible_delta_mode: bool = True
    no_delta_min_confidence: float = .70
    no_delta_min_bullish_score: float = .65
    risk_min_confidence: float = .55
    risk_min_bearish_score: float = .55
    risk_min_confirmations: int = 2
    watch_min_bullish_score: float = .25
    stale_confidence_penalty: float = .75
    very_stale_confidence_penalty: float = .40
    conflict_confidence_penalty: float = .82
    historical_min_confidence: float = .40


DECISION_CONFIG = DecisionConfig()
