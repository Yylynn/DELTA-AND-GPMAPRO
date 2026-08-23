import pandas as pd

from app.api.gpma2 import _series
from app.services.gpmapro_trace import TraceSnapshotService


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
