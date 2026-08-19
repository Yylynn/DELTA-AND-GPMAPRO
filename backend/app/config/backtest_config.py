from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionBacktestConfig:
    horizons: tuple[int, ...] = (5, 10, 20)
    confidence_buckets: tuple[float, ...] = (.40, .55, .70, .85)
    min_signature_samples: int = 3
    default_sampling_mode: str = "TRANSITION"


DECISION_BACKTEST_CONFIG = DecisionBacktestConfig()
