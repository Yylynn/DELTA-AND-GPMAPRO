import pandas as pd

from app.services.gpmaapro_engine import GpmaAproEngine, SIGNALS


def bars(count=160):
    close = pd.Series(range(100, 100 + count), dtype=float)
    return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=count, freq="B"), "open": close - .5, "high": close + 1, "low": close - 1, "close": close, "volume": 1000})


def test_gpmaapro_exposes_document_signal_and_drawing_contract():
    result = GpmaAproEngine().calculate(bars())
    expected = {"atr_26", "ma_120", "ma_250", "top_1_y", "bottom_2_y", *SIGNALS, *[f"{key}_raw" for key in SIGNALS], *[f"{key}_label_y" for key in SIGNALS]}
    assert expected <= set(result.columns)
    assert result.atr_26.iloc[:25].isna().all()
    assert all(result[key].dtype == bool for key in SIGNALS)


def test_gpmaapro_is_causal_at_as_of_boundary():
    source = bars(); cutoff = str(source.date.iloc[100].date())
    expected = GpmaAproEngine().calculate(source, cutoff)
    altered = source.copy(); altered.loc[101:, ["open", "high", "low", "close", "volume"]] *= 10
    pd.testing.assert_frame_equal(expected, GpmaAproEngine().calculate(altered, cutoff))


def test_gpmaapro_prefix_is_unchanged_when_future_bars_are_appended():
    source = bars(220)
    prefix = GpmaAproEngine().calculate(source.iloc[:160])
    full = GpmaAproEngine().calculate(source)
    pd.testing.assert_frame_equal(prefix, full.iloc[:160].reset_index(drop=True))
