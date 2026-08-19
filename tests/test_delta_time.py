from app.quant.delta_time import ConfigurableDeltaEngine, DeltaEventType, ManualDeltaEngine
def event(): return {"event_id":"e1","event_type":"HIGH","anchor_date":"2026-01-01","expected_date":"2026-02-01","tolerance_days":3}
def test_manual_window():
    out=ManualDeltaEngine([event()]).windows()[0]; assert out.event_type==DeltaEventType.HIGH; assert str(out.window_start)=="2026-01-29"; assert str(out.window_end)=="2026-02-04"; assert out.source=="manual"
def test_configurable_engine(): assert ConfigurableDeltaEngine.from_config({"events":[event()]}).windows()[0].cycle_type=="MANUAL"
