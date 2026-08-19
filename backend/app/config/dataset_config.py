from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetConfig:
    eligible_min_bars: int = 750
    limited_min_bars: int = 250
    readiness_eligible_symbols: int = 8
    readiness_transition_events: int = 200
    readiness_buy_events: int = 30
    readiness_watch_events: int = 50
    readiness_risk_events: int = 30
    readiness_delta_confirmations: int = 30


DATASET_CONFIG = DatasetConfig()
