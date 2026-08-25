import pandas as pd

from app.services.gpmaapro_engine import GpmaAproEngine, SIGNALS, _s01_price_reversal
from app.services.mai_language import MaiRuntime


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


def test_s01_uses_completed_body_average_and_previous_bull_midpoint():
    open_ = pd.Series([100.0] * 20 + [110.0])
    close = pd.Series([99.0] * 19 + [110.0, 107.0])
    body = (close - open_).abs()
    runtime = MaiRuntime(close.index)

    body_ma_20, price_reversal = _s01_price_reversal(
        close,
        open_,
        body,
        runtime,
    )

    assert body_ma_20.iloc[:19].isna().all()
    assert body_ma_20.iloc[19] == 1.45
    assert (
        runtime.trace["REF_OPEN_LAST_BULL"].iloc[20]
        + runtime.trace["REF_CLOSE_LAST_BULL"].iloc[20]
    ) / 2 == 105.0
    # 107 is below 100 + 110, but not below their midpoint.  This protects
    # against applying / 2 to the boolean comparison instead of to the sum.
    assert not bool(price_reversal.iloc[20])
