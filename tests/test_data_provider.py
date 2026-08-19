import pandas as pd
import pytest
from app.data.providers import validate_ohlcv
def test_validation_sorts_deduplicates_and_cleans():
    df=pd.DataFrame({"date":["2026-01-02","bad","2026-01-01","2026-01-01"],"open":[2,1,1,3],"high":[3,2,2,4],"low":[1,1,1,2],"close":[2,1,2,3],"volume":[1,1,1,1]})
    clean,q=validate_ohlcv(df); assert clean.date.tolist()==["2026-01-01","2026-01-02"]; assert q["missing_count"]==1; assert q["duplicate_count"]==1
def test_validation_rejects_invalid_high_low():
    df=pd.DataFrame({"date":["2026-01-01"],"open":[1],"high":[1],"low":[2],"close":[1],"volume":[0]})
    with pytest.raises(ValueError): validate_ohlcv(df)
