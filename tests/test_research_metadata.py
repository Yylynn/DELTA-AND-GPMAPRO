from types import SimpleNamespace

import pandas as pd

from app.services import research_metadata
from app.services.research_metadata import dataframe_identity, local_csv_provenance, provenance_sha256, research_run_metadata


def test_research_metadata_is_auditable_and_fingerprint_is_time_independent() -> None:
    kwargs = {
        "parameters": {"symbols": ["AAPL"], "cost_bps_per_side": 10},
        "data_provenance": {"source": "futu_opend_snapshot", "snapshot_id": "snapshot-1"},
        "stable_context": {"formula": "TEST_V1", "random_seed": 42},
    }
    first = research_run_metadata(**kwargs)
    second = research_run_metadata(**kwargs)
    assert first["fingerprint"] == second["fingerprint"]
    assert len(first["fingerprint"]) == 64
    assert first["generated_at"]
    assert first["app_version"] == "0.1.0"
    assert first["git_commit"]
    assert first["data_provenance"]["snapshot_id"] == "snapshot-1"
    assert first["workspace_fingerprint"]


def test_local_csv_provenance_changes_when_ohlcv_content_changes() -> None:
    frame = pd.DataFrame({"date": ["2026-01-02"], "open": [10], "high": [11], "low": [9], "close": [10], "volume": [100]})
    changed = frame.astype({"close": float}); changed.loc[0, "close"] = 10.5
    assert dataframe_identity(frame)["data_sha256"] != dataframe_identity(changed)["data_sha256"]
    provenance = local_csv_provenance({"AAPL": frame}, "1d")
    assert provenance["datasets"]["AAPL"]["bar_count"] == 1
    assert len(provenance["datasets"]["AAPL"]["data_sha256"]) == 64
    assert provenance_sha256(provenance, "AAPL") == provenance["datasets"]["AAPL"]["data_sha256"]
    assert len(provenance_sha256(provenance) or "") == 64


def test_clean_git_status_is_false_not_unknown(monkeypatch) -> None:
    monkeypatch.setattr(research_metadata.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert research_metadata._git_dirty() is False
