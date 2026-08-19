from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class DecisionEvent(BaseModel):
    symbol: str
    timeframe: str
    date: str
    state: Literal["BUY", "WATCH", "WAIT", "RISK"]
    confidence: float
    bullish_score: float
    bearish_score: float
    evidence_balance: str
    confirmations: dict
    confirmation_signature: str
    active_signal_codes: list[str]
    risk_factor_count: int
    conflict_count: int
    decision_codes: list[str]
    outcomes: dict

