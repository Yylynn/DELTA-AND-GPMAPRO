from dataclasses import dataclass


@dataclass(frozen=True)
class VolumeConfig:
    very_low_rvol: float = 0.60
    low_rvol: float = 0.85
    high_rvol: float = 1.20
    very_high_rvol: float = 1.80
    expanding_ratio: float = 1.15
    contracting_ratio: float = 0.85
    spike_rvol: float = 2.0
    dry_up_rvol: float = 0.5


VOLUME_CONFIG = VolumeConfig()
