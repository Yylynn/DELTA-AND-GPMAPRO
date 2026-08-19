from dataclasses import dataclass

@dataclass(frozen=True)
class DiagnosticsConfig:
    min_symbol_state_samples: int = 5
    min_pooled_samples: int = 10
    min_signature_samples: int = 10

DIAGNOSTICS_CONFIG = DiagnosticsConfig()
