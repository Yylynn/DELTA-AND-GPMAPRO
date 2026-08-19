import pandas as pd
import pytest
from app.services.spatial_statistics import SpatialStatisticsService
def bars():
    return pd.DataFrame({"date":pd.date_range("2026-01-01",periods=6),"close":[100,101,102,103,104,105],"high":[101,105,104,106,107,108],"low":[99,98,100,101,102,103],"atr":[2]*6})
def test_low_mfe_mae_and_targets():
    svc=SpatialStatisticsService(); out=svc.analyze(bars(),[{"event_id":"l","event_type":"LOW","expected_date":"2026-01-01"}],5,"2026-01-06")
    assert out["sample_count"]==1; assert out["samples"][0]["mfe_atr"]==4; assert out["samples"][0]["mae_atr"]==1; assert svc.targets(out,"LOW",100,2)["t1"]==108
def test_high_and_no_future_leakage():
    svc=SpatialStatisticsService(); out=svc.analyze(bars(),[{"event_id":"h","event_type":"HIGH","expected_date":"2026-01-01"}],5,"2026-01-04")
    assert out["sample_count"]==0
    with pytest.raises(ValueError): svc.analyze(bars(),[],7,"2026-01-06")
