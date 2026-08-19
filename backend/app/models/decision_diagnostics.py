from pydantic import BaseModel, Field

class DiagnosticsRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    sampling_mode: str = "TRANSITION"
