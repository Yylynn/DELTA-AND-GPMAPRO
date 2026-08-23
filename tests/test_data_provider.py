import pandas as pd
import pytest
from app.data.providers import validate_ohlcv
def test_validation_sorts_deduplicates_and_cleans():
    df=pd.DataFrame({"date":["2026-01-02","bad","2026-01-01","2026-01-01"],"open":[2,1,1,3],"high":[3,2,2,4],"low":[1,1,1,2],"close":[2,1,2,3],"volume":[1,1,1,1]})
    clean,q=validate_ohlcv(df); assert clean.date.tolist()==["2026-01-01","2026-01-02"]; assert q["missing_count"]==1; assert q["duplicate_count"]==1
def test_validation_rejects_invalid_high_low():
    df=pd.DataFrame({"date":["2026-01-01"],"open":[1],"high":[1],"low":[2],"close":[1],"volume":[0]})
    with pytest.raises(ValueError): validate_ohlcv(df)


def test_validation_flags_isolated_zero_volume_without_dropping_the_bar():
    df = pd.DataFrame({"date": ["2026-01-01", "2026-01-02", "2026-01-03"], "open": [10, 10, 10], "high": [11, 11, 11], "low": [9, 9, 9], "close": [10, 10, 10], "volume": [100, 0, 120]})
    clean, quality = validate_ohlcv(df)
    assert len(clean) == 3
    assert quality["zero_volume_status"] == "ISOLATED"
    assert quality["zero_volume_count"] == 1
    assert quality["max_consecutive_zero_volume"] == 1
    assert quality["quality"] == "需复核"


def test_validation_distinguishes_consecutive_and_all_zero_volume():
    base = {"date": ["2026-01-01", "2026-01-02", "2026-01-03"], "open": [10, 10, 10], "high": [11, 11, 11], "low": [9, 9, 9], "close": [10, 10, 10]}
    _, consecutive = validate_ohlcv(pd.DataFrame({**base, "volume": [100, 0, 0]}))
    _, all_zero = validate_ohlcv(pd.DataFrame({**base, "volume": [0, 0, 0]}))
    assert consecutive["zero_volume_status"] == "CONSECUTIVE"
    assert consecutive["max_consecutive_zero_volume"] == 2
    assert all_zero["zero_volume_status"] == "ALL_ZERO"
    assert all_zero["max_consecutive_zero_volume"] == 3
