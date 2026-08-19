import pandas as pd

from app.services.gpmapro_engine import GpmaProEngine


def bars(count=80):
    dates = pd.date_range("2025-01-01", periods=count, freq="B")
    close = pd.Series(range(100, 100 + count), dtype=float)
    return pd.DataFrame({"date": dates, "open": close - .5, "high": close + 1, "low": close - 1, "close": close, "volume": [1000] * (count - 1) + [1500]})


def test_snapshot_exposes_the_standardized_gpmapro_contract():
    out = GpmaProEngine().snapshot(bars(), "aapl", "1d")
    assert out["symbol"] == "AAPL"
    assert set(out) == {"symbol", "timeframe", "as_of", "trend", "volume", "filters", "signals", "divergence"}
    assert out["volume"]["vol_strong"] is True
    # JUSTIN WEAPON's MA120 remains DRAWNULL until the full window is ready.
    assert out["trend"]["bull_bg"] is False


def test_calculation_is_causal_when_an_as_of_cutoff_is_used():
    engine = GpmaProEngine(); source = bars(100); cutoff = str(source.date.iloc[60].date())
    truncated = engine.calculate(source, cutoff)
    mutated = source.copy(); mutated.loc[61:, ["open", "high", "low", "close", "volume"]] *= 10
    recalculated = engine.calculate(mutated, cutoff)
    pd.testing.assert_frame_equal(truncated, recalculated)


def test_volume_and_gap_filters_follow_the_source_thresholds():
    source = bars(30); source.loc[29, "open"] = source.loc[28, "close"] * 1.09
    result = GpmaProEngine().calculate(source).iloc[-1]
    assert result.vol_strong
    assert not result.gap_ok
    assert not result.buy_ok
