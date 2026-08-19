import pandas as pd
from app.services.gpmapro_engine import GpmaProEngine, _ref_dynamic


def bars(count=80):
    dates = pd.date_range("2024-01-01", periods=count, freq="B")
    close = pd.Series(range(100, 100 + count), dtype=float)
    return pd.DataFrame({"date": dates, "open": close - .5, "high": close + 1, "low": close - 1, "close": close, "volume": 1000})


def test_gpmapro_calculation_exposes_atr_and_all_divergence_fields():
    result = GpmaProEngine().calculate(bars())
    expected = {"atr_26", "top_1_raw", "top_2_raw", "top_3_raw", "bottom_1_raw", "bottom_2_raw", "bottom_3_raw", "N1", "N2", "HH", "MHD", "PP", "MMH", "TBL10", "BBL10", "TBL1", "BBL1"}
    assert expected <= set(result.columns)
    # Futu MA(26) follows complete-window semantics, so ATR is DRAWNULL
    # during its 25-bar warm-up period.
    assert result.atr_26.iloc[:25].isna().all()
    assert result.atr_26.iloc[25:].notna().all()
    assert all(result[column].dtype == bool for column in {"top_1_raw", "top_2_raw", "top_3_raw", "bottom_1_raw", "bottom_2_raw", "bottom_3_raw", "TBL10", "BBL10", "TBL1", "BBL1"})


def test_divergence_fields_are_point_in_time():
    data = bars(80); engine = GpmaProEngine(); full = engine.calculate(data)
    as_of = str(data.date.iloc[55].date())
    truncated = engine.calculate(data, as_of=as_of).iloc[-1]
    fields = ["top_1_raw", "top_2_raw", "top_3_raw", "bottom_1_raw", "bottom_2_raw", "bottom_3_raw"]
    assert {field: bool(full.iloc[55][field]) for field in fields} == {field: bool(truncated[field]) for field in fields}


def test_series_contract_exposes_chartable_formula_inputs():
    result = GpmaProEngine().calculate(bars())
    expected = {"close", "ma_120", "ma_250", "diff", "dea", "macd", "volume_ratio", "buy_ok", "sell_ok", "b1_raw", "s1_raw"}
    assert expected <= set(result.columns)


def test_main_chart_contract_matches_formula_line_colours_and_coordinates():
    result = GpmaProEngine().calculate(bars(140))
    expected = {
        "ema_8_red", "ema_10_red", "ema_12_red", "ema_15_red", "ema_20_red",
        "ema_40_red", "ema_45_red", "ema_50_red", "ema_55_red", "ema_60_red",
        "b1_label_y", "s2_label_y", "top_face", "bottom_face", "top_arrow_2_y", "bottom_arrow_3_y",
    }
    assert expected <= set(result.columns)
    row = result.iloc[-1]
    assert bool(row.ema_8_red) == bool(row.ema_8 > row.ema_10)
    assert bool(row.ema_20_red) == bool(row.ema_15 > row.ema_20)
    assert bool(row.ema_60_red) == bool(row.ema_55 > row.ema_60)


def test_chart_display_annotations_are_point_in_time():
    source = bars(110); engine = GpmaProEngine(); full = engine.calculate(source)
    cutoff = str(source.date.iloc[75].date())
    truncated = engine.calculate(source, as_of=cutoff).iloc[-1]
    fields = ["top_1", "top_2", "top_3", "bottom_1", "bottom_2", "bottom_3", "top_face", "bottom_face"]
    assert {field: bool(full.iloc[75][field]) for field in fields} == {field: bool(truncated[field]) for field in fields}


def test_dynamic_ref_uses_each_bar_barslast_offset_not_forward_fill():
    values = pd.Series([10., 20., 30., 40., 50.])
    offsets = pd.Series([float("nan"), 0., 1., 2., 1.])
    actual = _ref_dynamic(values, offsets)
    assert actual.isna().iloc[0]
    assert actual.iloc[1:].tolist() == [20., 20., 20., 40.]


def test_display_coordinates_are_exact_formula_offsets_when_triggered():
    result = GpmaProEngine().calculate(bars(140))
    checks = (("b1_label_y", result.low - .5 * result.atr_26), ("s2_label_y", result.high + .5 * result.atr_26), ("top_face_y", result.close + 1.5 * result.atr_26), ("bottom_face_y", result.close - 1.5 * result.atr_26), ("top_arrow_2_y", result.open + .3 * result.atr_26), ("bottom_arrow_3_y", result.low - .3 * result.atr_26))
    for coordinate, expected in checks:
        visible = result[coordinate].notna()
        assert (result.loc[visible, coordinate] == expected.loc[visible]).all()


def test_real_futu_snapshot_keeps_the_known_aapl_ema_contract_when_available():
    from pathlib import Path
    snapshots = Path(__file__).resolve().parents[1].glob("data/futu_snapshots/US_AAPL_1D_QFQ_*.csv")
    snapshot = max(snapshots, default=None, key=lambda path: path.stat().st_size)
    if snapshot is None:
        return
    source = pd.read_csv(snapshot)
    result = GpmaProEngine().calculate(source)
    row = result.loc[result.date.eq(pd.Timestamp("2023-06-07"))].iloc[0]
    assert round(row.ema_8, 3) == 175.372
    assert round(row.ema_10, 3) == 174.924
    assert round(row.ema_15, 3) == 173.819
    assert round(row.ema_20, 3) == 172.759
