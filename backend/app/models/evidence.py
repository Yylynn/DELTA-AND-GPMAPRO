"""Stable contracts for the research-only Market Evidence layer."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

Direction = Literal["BULLISH", "BEARISH", "NEUTRAL", "MIXED", "UNKNOWN"]
EvidenceStatus = Literal["ACTIVE", "RECENT", "EXPIRED", "AVAILABLE", "UNAVAILABLE"]


class EvidenceItem(BaseModel):
    id: str
    source: Literal["DELTA", "GPMAPRO", "VOLUME", "BACKTEST", "DATA", "NEWS"]
    category: Literal["TIME", "TREND", "MOMENTUM", "VOLATILITY", "VOLUME", "PRICE_VOLUME", "SIGNAL", "HISTORICAL", "DATA_QUALITY", "NEWS_SENTIMENT", "CATALYST"]
    label: str
    direction: Direction
    strength: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    weight: float = Field(ge=0)
    status: EvidenceStatus
    as_of: str
    details: dict[str, Any] = Field(default_factory=dict)
