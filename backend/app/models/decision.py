from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class RiskFactor(BaseModel):
    code: str
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    message: str


class Confirmations(BaseModel):
    delta: bool
    trend: bool
    signal: bool
    volume: bool
    historical: bool
    news: bool = False
    count: int = Field(ge=0, le=6)


class DecisionSnapshot(BaseModel):
    symbol: str
    timeframe: str
    as_of: str
    state: Literal["BUY", "WATCH", "WAIT", "RISK"]
    confidence: float = Field(ge=0, le=1)
    scores: dict[str, float]
    evidence_balance: str
    confirmations: Confirmations
    reasons: list[str]
    missing_conditions: list[str]
    risk_factors: list[RiskFactor]
    data_quality: dict
    decision_trace: dict
    news_trace: dict = Field(default_factory=dict)
