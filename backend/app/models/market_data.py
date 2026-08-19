from datetime import date
from pydantic import BaseModel
class OhlcvBar(BaseModel):
    date: date; open: float; high: float; low: float; close: float; volume: float
class DataQuality(BaseModel):
    symbol: str; start_date: date; end_date: date; bar_count: int; missing_count: int; duplicate_count: int; quality: str
