import json
import pandas as pd
from app.data.providers import CsvDataProvider
from app.services.batch_import import import_batch
from app.services.dataset import coverage, eligibility, snapshot
from app.services.readiness import readiness


def csv(start="2020-01-01", count=3):
    dates = pd.date_range(start, periods=count, freq="B")
    return pd.DataFrame({"date": dates, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}).to_csv(index=False).encode()


def test_batch_import_is_isolated_and_classifies_history(tmp_path):
    provider = CsvDataProvider(tmp_path)
    result = import_batch(provider, [("AAA.csv", csv(count=750)), ("bad.csv", b"wrong,column\n1,2"), ("BBB.csv", csv(count=250))])
    assert result["imported"] == 2 and result["rejected"] == 1
    assert eligibility(750) == "ELIGIBLE" and eligibility(250) == "LIMITED" and eligibility(249) == "INELIGIBLE"


def test_snapshot_fingerprints_are_deterministic_and_delta_sensitive(tmp_path):
    provider = CsvDataProvider(tmp_path); provider.save("AAA", csv(count=3))
    events = [{"event_id": "1", "symbol": "AAA", "event_type": "LOW", "anchor_date": "2020-01-01", "expected_date": "2020-01-01"}]
    first, second = snapshot(provider, events), snapshot(provider, events)
    assert first["symbols"][0]["sha256"] == second["symbols"][0]["sha256"]
    assert first["delta_event_fingerprint"] != snapshot(provider, [{**events[0], "event_type": "HIGH"}])["delta_event_fingerprint"]


def test_readiness_requires_all_measurement_thresholds():
    universe = [{"research_eligibility": "ELIGIBLE"}]
    result = readiness(universe, {"total_events": 25, "pooled": {"BUY": {"sample_count": 2}, "WATCH": {"sample_count": 11}, "RISK": {"sample_count": 4}}, "delta_funnel": {"decision_confirmations": 0}})
    assert result["status"] == "NOT_READY" and not result["requirements"]["eligible_symbols"]["passed"]


def test_coverage_requires_diverse_eligible_research_basket(tmp_path):
    provider = CsvDataProvider(tmp_path)
    for symbol in ("SPY", "QQQ", "IWM", "XLF", "XLE", "XLV", "XLI", "XLU"):
        provider.save(symbol, csv(count=750))
    result = coverage(provider)
    assert result["status"] == "READY" and result["basket_coverage"] == 8
