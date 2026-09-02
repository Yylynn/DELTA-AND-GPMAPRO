import importlib

import numpy as np
import pandas as pd

from app.api.gpma2 import _local_formula_frame, _series
from app.services.gpmaapro_engine import GpmaAproEngine, SIGNALS
from app.services.gpmapro_trace import TraceSnapshotService

gpma2_api = importlib.import_module("app.api.gpma2")


def bars(count=300):
    x = np.arange(count, dtype=float)
    close = pd.Series(100 + x * .08 + np.sin(x / 8) * 7)
    open_ = close + np.cos(x / 5)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=count, freq="B"),
        "open": open_, "high": np.maximum(open_, close) + 1.2,
        "low": np.minimum(open_, close) - 1.2, "close": close,
        "volume": 1000 + x,
    })


def test_gpma2_maps_futu_outputs_to_chart_lines_and_formula_nodes():
    frame = pd.DataFrame({
        "date": ["2025-01-02"], "close": [100.0], "E8R": [101.0], "E8G": [float("nan")],
        "E10R": [float("nan")], "E10G": [99.0], "EM120": [90.0], "EM250": [80.0],
        "MDIFF": [1.0], "MDEA": [.5], "MMACD": [1.0], "LINE1": [98.0], "LINE14": [103.0],
    })
    row = _series(frame)[0]
    assert row["ema_8"] == 101.0 and row["ema_8_red"] is True
    assert row["ema_10"] == 99.0 and row["ema_10_red"] is False
    assert row["ma_120"] == 90.0 and row["close"] == 100.0
    assert row["draw_nodes"] == [
        {"kind": "text", "formula": "DRAWTEXT", "text": "B01", "price": 98.0},
        {"kind": "icon", "formula": "DRAWICON", "icon_id": 4, "visual": "top-face", "price": 103.0, "direction": "top"},
    ]


def test_gpma2_icon_semantics_distinguish_faces_from_arrows():
    frame = pd.DataFrame({
        "date": ["2025-01-02"], "close": [100.0], "EM120": [90.0], "EM250": [80.0],
        "MDIFF": [1.0], "MDEA": [.5], "MMACD": [1.0], "LINE14": [104.0],
        "LINE15": [96.0], "LINE16": [105.0], "LINE17": [95.0],
    })
    nodes = _series(frame)[0]["draw_nodes"]
    assert [(node["icon_id"], node["visual"]) for node in nodes] == [
        (4, "top-face"), (5, "bottom-face"), (2, "top-arrow-2"), (1, "bottom-arrow-2"),
    ]


def test_trace_storage_keeps_gpma2_separate_from_gpmapro(tmp_path):
    trace = TraceSnapshotService(tmp_path, namespace="GPMA2").import_frame(pd.DataFrame({"date": ["2025-01-02"], "E8R": [1.0]}))
    assert trace["trace_id"].startswith("GPMA2_TRACE_")


def test_local_gpma2_series_does_not_call_opend(monkeypatch, tmp_path):
    source = bars()
    monkeypatch.setattr(gpma2_api, "bars_for_source", lambda *_: (source, {"code": "US.TEST", "provider": "yahoo"}))
    monkeypatch.setattr(gpma2_api, "traces", TraceSnapshotService(tmp_path, namespace="GPMA2"))

    response = gpma2_api.gpma2_series("TEST")

    assert response["calculation_source"] == "local_gpmaapro_v1"
    assert response["reconciliation_status"] == "not_reconciled"
    assert response["trace_status"] == "LOCAL_RENDERER_FALLBACK"
    assert len(response["series"]) == len(source)
    assert response["series"][-1]["ema_8"] is not None
    assert response["series"][118]["ma_120"] is None
    assert response["series"][119]["ma_120"] is not None


def test_local_colour_segments_follow_gpma2_mai_pair_rules():
    data = GpmaAproEngine().calculate(bars())
    frame = _local_formula_frame(data)
    row, native = frame.iloc[-1], data.iloc[-1]
    expected = {8: native.ema_8 > native.ema_10, 10: native.ema_10 > native.ema_12, 12: native.ema_12 > native.ema_15, 15: native.ema_15 > native.ema_20, 20: native.ema_15 > native.ema_20, 40: native.ema_40 > native.ema_45, 45: native.ema_45 > native.ema_50, 50: native.ema_50 > native.ema_55, 55: native.ema_55 > native.ema_60, 60: native.ema_55 > native.ema_60}
    for period, is_red in expected.items():
        assert pd.notna(row[f"E{period}R"]) is bool(is_red)
        assert pd.notna(row[f"E{period}G"]) is (not bool(is_red))


def test_local_signal_coordinates_follow_trace_contract():
    data = GpmaAproEngine().calculate(bars())
    frame = _local_formula_frame(data)
    for signal in SIGNALS:
        active = data[signal]
        if not active.any():
            continue
        expected = data.loc[active, "low"] - .5 * data.loc[active, "atr_26"] if signal.startswith("b") else data.loc[active, "high"] + .5 * data.loc[active, "atr_26"]
        pd.testing.assert_series_equal(frame.loc[active, f"TRACE_{signal.upper()}"], expected, check_names=False)


def test_saved_complete_reference_updates_reconciliation_status(monkeypatch, tmp_path):
    source = bars()
    service = TraceSnapshotService(tmp_path, namespace="GPMA2")
    local = _local_formula_frame(GpmaAproEngine().calculate(source))
    manifest = service.import_frame(local, metadata={"symbol": "US.TEST", "timeframe": "1d", "script_sha256": "futu-reference"})
    monkeypatch.setattr(gpma2_api, "bars_for_source", lambda *_: (source, {"code": "US.TEST", "provider": "yahoo"}))
    monkeypatch.setattr(gpma2_api, "traces", service)

    response = gpma2_api.gpma2_series("TEST")
    audit = gpma2_api.reconciliation("TEST", manifest["trace_id"])

    assert response["reconciliation_status"] == "matched"
    assert response["reconciliation_trace_id"] == manifest["trace_id"]
    assert audit["reconciliation_status"] == "matched"
    assert audit["comparison"]["compared_fields"] == audit["comparison"]["required_fields"]
