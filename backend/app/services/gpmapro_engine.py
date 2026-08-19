"""GPMAPRO US v1 indicators and research signals.

This is a Python translation of the supplied MaiLanguage formula.  It accepts
only OHLCV bars available at the requested ``as_of`` point; no calculation
looks ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.mai_language import MaiRuntime
from app.services.volume_monitor import add_volume_metrics


REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}
EMA_PERIODS = (8, 10, 12, 15, 20, 40, 45, 50, 55, 60)


def _cross_above(left: pd.Series, right: pd.Series) -> pd.Series:
    return (left > right) & (left.shift(1) <= right.shift(1))


def _barslast(condition: pd.Series) -> pd.Series:
    result: list[float] = []
    last: int | None = None
    for index, value in enumerate(condition.fillna(False)):
        if bool(value):
            last = index
        result.append(np.nan if last is None else index - last)
    return pd.Series(result, index=condition.index, dtype="float64")


def _count_recent(signal: pd.Series, window: int = 5) -> pd.Series:
    return signal.astype(int).rolling(window, min_periods=1).sum()


def _ref_dynamic(values: pd.Series, offsets: pd.Series) -> pd.Series:
    """MaiLanguage REF(X, N) when N is a per-bar BARSLAST expression.

    A forward-filled last event is not equivalent: the offset is evaluated on
    every current bar and selects a historical value relative to that bar.
    """
    result: list[float] = []
    for index, offset in enumerate(offsets):
        if pd.isna(offset):
            result.append(np.nan)
            continue
        target = index - int(offset)
        result.append(np.nan if target < 0 else values.iloc[target])
    return pd.Series(result, index=values.index, dtype="float64")


def _rolling_extreme(values: pd.Series, widths: pd.Series, *, maximum: bool) -> pd.Series:
    """Match the formula language's variable-window HHV/LLV without look-ahead."""
    result: list[float] = []
    for index, width in enumerate(widths):
        count = index + 1 if pd.isna(width) else max(1, int(width))
        window = values.iloc[max(0, index - count + 1):index + 1]
        result.append(float(window.max() if maximum else window.min()))
    return pd.Series(result, index=values.index, dtype="float64")


class GpmaProEngine:
    """Compute the supplied GPMAPRO US v1 formula on chronological OHLCV."""

    def calculate(self, bars: pd.DataFrame, as_of: str | None = None) -> pd.DataFrame:
        if not REQUIRED_COLUMNS.issubset(bars.columns):
            missing = ", ".join(sorted(REQUIRED_COLUMNS - set(bars.columns)))
            raise ValueError(f"GPMAPRO requires OHLCV columns: {missing}")
        data = bars.copy().sort_values("date").reset_index(drop=True)
        data["date"] = pd.to_datetime(data["date"])
        if as_of:
            data = data[data["date"] <= pd.Timestamp(as_of)].copy().reset_index(drop=True)
        if data.empty:
            raise ValueError("No OHLCV data is available at as_of")
        for column in REQUIRED_COLUMNS - {"date"}:
            data[column] = pd.to_numeric(data[column], errors="coerce")
        if data[list(REQUIRED_COLUMNS - {"date"})].isna().any().any():
            raise ValueError("GPMAPRO received invalid OHLCV data")

        close, high, low, open_, volume = (data[name] for name in ("close", "high", "low", "open", "volume"))
        rt = MaiRuntime(data.index)
        for period in EMA_PERIODS:
            data[f"ema_{period}"] = rt.ema(close, period, f"E{period}")
        data["ma_120"] = rt.ma(close, 120, "E120")
        data["ma_250"] = rt.ma(close, 250, "E250")
        data["diff"] = rt.put("DIFF", rt.ema(close, 12, "DIFF_EMA12") - rt.ema(close, 26, "DIFF_EMA26"))
        data["dea"] = rt.ema(data["diff"], 9, "DEA")
        data["macd"] = rt.put("MACD", (data["diff"] - data["dea"]) * 2)
        previous_close = rt.ref(close, 1, "REF_CLOSE_1")
        true_range = pd.concat([high - low, (previous_close - high).abs(), (previous_close - low).abs()], axis=1).max(axis=1)
        data["atr_26"] = rt.ma(rt.put("GTR", true_range), 26, "ATR")
        # GPMAPRO JUSTIN WEAPON uses the literal ABS(OPEN-CLOSE), with no
        # US_v1 body floor or volume/gap/trend filters.
        data["body"] = (open_ - close).abs()

        data = add_volume_metrics(data)
        data["vol_ma_20"] = data["volume_ma20"]
        data["volume_ratio"] = data["relative_volume"]
        data["vol_ok"] = volume > data["vol_ma_20"] * 1.05
        data["vol_strong"] = volume > data["vol_ma_20"] * 1.20
        data["gap_rate"] = np.where(previous_close > 0, (open_ - previous_close).abs() / previous_close, np.nan)
        data["gap_ok"] = data["gap_rate"].lt(.08).fillna(False)
        data["range_ok"] = (high - low) < data["atr_26"] * 3.20
        data["bull_bg"] = (close > data["ma_120"]) & (data["ema_20"] > data["ema_60"])
        data["bull_strong"] = data["bull_bg"] & (data["ma_120"] > data["ma_250"])
        data["bear_bg"] = (close < data["ma_120"]) & (data["ema_20"] < data["ema_60"])
        data["top_confirm"] = (close < data["ema_8"]) | (data["ema_8"] < data["ema_10"]) | (close < data["ema_20"])
        data["bottom_confirm"] = (close > data["ema_8"]) | (data["ema_8"] > data["ema_10"]) | (close > data["ema_20"])
        data["buy_ok"] = data["vol_ok"] & data["gap_ok"] & data["range_ok"] & data["bull_bg"]
        data["buy_strong_ok"] = data["vol_strong"] & data["gap_ok"] & data["range_ok"] & data["bull_strong"]
        data["sell_ok"] = data["gap_ok"] & data["range_ok"]

        # Named DRAWNULL output lines exposed by Futu's MyLang calculation.
        # Keeping these names makes the OpenD TRACE CSV directly comparable.
        for period, left, right in ((8, 8, 10), (10, 10, 12), (12, 12, 15), (15, 15, 20),
                                    (20, 15, 20), (40, 40, 45), (45, 45, 50),
                                    (50, 50, 55), (55, 55, 60), (60, 55, 60)):
            rising = data[f"ema_{left}"] > data[f"ema_{right}"]
            data[f"E{period}R"] = data[f"ema_{period}"].where(rising)
            data[f"E{period}G"] = data[f"ema_{period}"].where(~rising)

        body = data["body"]
        zshc0 = (data.ema_8 > data.ema_10) & (data.ema_10 > data.ema_12) & (data.ema_12 > data.ema_15) & (data.ema_15 > data.ema_20) & (data.ema_55 < data.ema_60) & (data.ema_8 > data.ema_60) & (close > data.ema_60) & (data.dea.shift(10) < 0) & (((low - close).abs() / body > 1.5) | ((open_ < previous_close) & (close > (open_ - close).abs().shift(1) / 2))) & ((low < data.ema_20) & (close > data.ema_20) | (low < data.ema_15) & (close > data.ema_15) | (low < data.ema_8) & (close > data.ema_8) | (low < data.ema_10) & (close > data.ema_10) | (low < data.ema_12) & (close > data.ema_12))
        gstp0 = (data.ema_12 > data.ema_15) & (data.ema_15 > data.ema_20) & (data.ema_8 > data.ema_60) & (data.dea > 0) & (close > open_) & ((open_ < data.ema_20) | (low < data.ema_20) | (low.shift(1) < data.ema_20)) & (close > data.ema_20) & (high.ne(high.rolling(10, min_periods=1).max())) & ((data.macd <= 0) | (data.dea.shift(3) >= 0))
        gltp0 = (data.ema_40 > data.ema_45) & (data.ema_45 > data.ema_50) & (data.ema_50 > data.ema_55) & (data.ema_55 > data.ema_60) & (data.ema_20 > data.ema_60) & ((high - close) / body < 1.5) & (close >= open_) & ((open_ < data.ema_60) | (low < data.ema_60) | (low.shift(1) < data.ema_60)) & (close > data.ema_60) & high.ne(high.rolling(10, min_periods=1).max()) & (data.dea >= 0)
        gsdp0 = (data.ema_15 < data.ema_20) & (data.ema_20 < data.ema_60) & (data.dea < 0) & (open_ > close) & ((open_ > data.ema_20) | (high > data.ema_20) | (high.shift(1) > data.ema_20)) & (close < data.ema_20) & low.ne(low.rolling(10, min_periods=1).min())
        gldp0 = ((data.ema_20 < data.ema_60) & (data.ema_55 < data.ema_60) | (data.ema_15 < data.ema_20) & (data.ema_20 < data.ema_60)) & (data.dea < 0) & (open_ > close) & ((close - low) / body < 1.5) & ((open_ > data.ema_60) | (high > data.ema_60) | (high.shift(1) > data.ema_60)) & (close < data.ema_60) & low.ne(low.rolling(10, min_periods=1).min())
        data["b1_raw"], data["b2_raw"], data["b3_raw"] = zshc0, gstp0, gltp0
        data["s2_raw"], data["s1_raw"] = gsdp0, gldp0

        # Match the supplied formula's prior MACD-cycle extrema exactly.  The
        # state is carried only from completed JC/SC cycles, so no future bars
        # are consulted when evaluating a point-in-time row.
        jc = rt.cross(data["diff"], data["dea"], "JC")
        sc = rt.cross(data["dea"], data["diff"], "SC")
        n1 = rt.put("N1", rt.barslast(jc.shift(1, fill_value=False).astype(bool), "BARSLAST_REF_JC_1") + 1)
        n2 = rt.put("N2", rt.barslast(sc.shift(1, fill_value=False).astype(bool), "BARSLAST_REF_SC_1") + 1)
        cycle_high = rt.hhv(high, n1, "HHV_H_N1")
        cycle_high_macd = rt.hhv(data["macd"], n1, "HHV_MACD_N1")
        cycle_low = rt.llv(low, n2, "LLV_L_N2")
        cycle_low_macd = rt.llv(data["macd"], n2, "LLV_MACD_N2")
        hh = rt.ref(cycle_high, rt.barslast(sc, "BARSLAST_SC"), "HH")
        mhd = rt.ref(cycle_high_macd, rt.barslast(sc, "BARSLAST_SC_MHD"), "MHD")
        ll = rt.ref(cycle_low, rt.barslast(jc, "BARSLAST_JC"), "LL")
        mld = rt.ref(cycle_low_macd, rt.barslast(jc, "BARSLAST_JC_MLD"), "MLD")
        peak = (data.macd.shift(1) > data.macd.shift(2)) & (data.macd.shift(1) > data.macd)
        trough = (data.macd.shift(1) < data.macd.shift(2)) & (data.macd.shift(1) < data.macd)
        pp = rt.ref(high.shift(1), rt.barslast(peak, "BARSLAST_MACD_PEAK"), "PP")
        mmh = rt.ref(data.macd.shift(1), rt.barslast(peak, "BARSLAST_MACD_PEAK_MMH"), "MMH")
        tt = rt.ref(low.shift(1), rt.barslast(trough, "BARSLAST_MACD_TROUGH"), "TT")
        mml = rt.ref(data.macd.shift(1), rt.barslast(trough, "BARSLAST_MACD_TROUGH_MML"), "MML")
        tbl10 = rt.put("TBL10", peak & (data.macd > 0) & (pp > hh) & (mmh < mhd))
        bbl10 = rt.put("BBL10", trough & (data.macd < 0) & (tt < ll) & (mml > mld) & (high < data.ema_20))
        kh, macdh = rt.ref(rt.hhv(high, 10, "HHV_HIGH_10"), 2, "KH"), rt.ref(rt.hhv(data.macd, 10, "HHV_MACD_10"), 2, "MACDH")
        kl, macdl = rt.ref(rt.llv(low, 10, "LLV_LOW_10"), 2, "KL"), rt.ref(rt.llv(data.macd, 10, "LLV_MACD_10"), 2, "MACDL")
        tbl20 = rt.put("TBL20", (data.dea > 0) & (high > kh) & (data.macd < macdh) & (data.macd < data.macd.shift(1)) & ((close - open_).shift(1) > 0) & (low > data.ema_8) & (open_ > close))
        bbl20 = rt.put("BBL20", (data.dea < 0) & (low < kl) & (data.macd > macdl) & (data.macd > data.macd.shift(1)) & ((close - open_).shift(1) < 0) & (high < data.ema_8) & (open_ < close))
        tbl30 = rt.put("TBL30", (data.macd < data.macd.shift(1)) & high.eq(rt.hhv(high, 10, "HHV_HIGH_10_TBL30")) & (low > data.ema_8) & (open_ > close))
        bbl30 = rt.put("BBL30", (data.macd > data.macd.shift(1)) & low.eq(rt.llv(low, 10, "LLV_LOW_10_BBL30")) & (high < data.ema_8) & (open_ < close))
        data["top_1_raw"], data["bottom_1_raw"] = rt.put("TBL1", tbl10), rt.put("BBL1", bbl10)
        data["top_2_raw"], data["bottom_2_raw"] = rt.put("TBL2", tbl20), rt.put("BBL2", bbl20)
        data["top_3_raw"], data["bottom_3_raw"] = rt.put("TBL3", tbl30), rt.put("BBL3", bbl30)
        data["b1"] = data.b1_raw & _count_recent(data.b1_raw).lt(2)
        data["b2"] = data.b2_raw & _count_recent(data.b2_raw).lt(2) & _count_recent(data.b3_raw).lt(1)
        data["b3"] = data.b3_raw & _count_recent(data.b3_raw).lt(2)
        data["s1"] = data.s1_raw & _count_recent(data.s1_raw).lt(2)
        data["s2"] = data.s2_raw & _count_recent(data.s2_raw).lt(2) & _count_recent(data.s1_raw).lt(1) & ((_count_recent(data.bottom_2_raw, 10) + _count_recent(data.bottom_3_raw, 10)) < 2)

        # Main-chart display contract.  These fields mirror the formula's
        # DRAWTEXT/DRAWICON clauses, rather than exposing a raw condition as a
        # visible alert.  Coordinates are price coordinates; the frontend only
        # resolves overlaps caused by multiple same-day annotations.
        # E20 and E60 intentionally inherit the preceding pair's direction.
        # This asymmetric relationship is explicit in the MaiLanguage source.
        ema_red_rules = {
            "ema_8": data["ema_8"] > data["ema_10"],
            "ema_10": data["ema_10"] > data["ema_12"],
            "ema_12": data["ema_12"] > data["ema_15"],
            "ema_15": data["ema_15"] > data["ema_20"],
            "ema_20": data["ema_15"] > data["ema_20"],
            "ema_40": data["ema_40"] > data["ema_45"],
            "ema_45": data["ema_45"] > data["ema_50"],
            "ema_50": data["ema_50"] > data["ema_55"],
            "ema_55": data["ema_55"] > data["ema_60"],
            "ema_60": data["ema_55"] > data["ema_60"],
        }
        for ema, condition in ema_red_rules.items():
            data[f"{ema}_red"] = condition
        data["b1_label_y"] = (low - .5 * data["atr_26"]).where(data["b1"])
        data["b2_label_y"] = (low - .5 * data["atr_26"]).where(data["b2"])
        data["b3_label_y"] = (low - .5 * data["atr_26"]).where(data["b3"])
        data["s1_label_y"] = (high + .5 * data["atr_26"]).where(data["s1"])
        data["s2_label_y"] = (high + .5 * data["atr_26"]).where(data["s2"])
        for number, raw in ((1, "top_1_raw"), (2, "top_2_raw"), (3, "top_3_raw"), (1, "bottom_1_raw"), (2, "bottom_2_raw"), (3, "bottom_3_raw")):
            prefix = "top" if raw.startswith("top") else "bottom"
            data[f"{prefix}_{number}"] = data[raw] & _count_recent(data[raw]).lt(2)
        data["top_face"] = data["top_1"] & (close > data["ema_10"]) & (close < open_)
        data["bottom_face"] = data["bottom_1"] & (close < data["ema_10"]) & (close > open_)
        data["top_face_y"] = (close + 1.5 * data["atr_26"]).where(data["top_face"])
        data["bottom_face_y"] = (close - 1.5 * data["atr_26"]).where(data["bottom_face"])
        for number in (2, 3):
            data[f"top_arrow_{number}_y"] = (open_ + .3 * data["atr_26"]).where(data[f"top_{number}"])
            data[f"bottom_arrow_{number}_y"] = (low - .3 * data["atr_26"]).where(data[f"bottom_{number}"])
        # Numeric-only outputs in the Futu GPMAPRO_TRACE clone.  A zero means
        # the corresponding DRAWTEXT/DRAWICON clause did not draw on this bar;
        # a non-zero value is the exact formula price coordinate.  Keeping this
        # contract alongside the UI fields lets reconciliation compare the
        # final drawing clauses, not just their intermediate conditions.
        trace_nodes = {
            "TRACE_B1": data["b1_label_y"],
            "TRACE_B2": data["b2_label_y"],
            "TRACE_B3": data["b3_label_y"],
            "TRACE_S1": data["s1_label_y"],
            "TRACE_S2": data["s2_label_y"],
            "TRACE_TOP1": data["top_face_y"],
            "TRACE_BOT1": data["bottom_face_y"],
            "TRACE_TOP2": data["top_arrow_2_y"],
            "TRACE_BOT2": data["bottom_arrow_2_y"],
            "TRACE_TOP3": data["top_arrow_3_y"],
            "TRACE_BOT3": data["bottom_arrow_3_y"],
        }
        for name, coordinate in trace_nodes.items():
            data[name] = coordinate.fillna(0.0)
        # Named primitive values are intentionally retained for TRACE exports
        # and per-date reconciliation.  Formula names do not replace the UI's
        # stable snake_case contract.
        trace_columns = {name: value for name, value in rt.trace.items() if name not in data}
        if trace_columns:
            data = pd.concat([data, pd.DataFrame(trace_columns, index=data.index)], axis=1)
        for column in data.columns:
            if column.endswith(("_ok", "_bg", "_strong", "_confirm", "_raw", "_red")) or column in {"b1", "b2", "b3", "s1", "s2", "top_1", "top_2", "top_3", "bottom_1", "bottom_2", "bottom_3", "top_face", "bottom_face"}:
                data[column] = data[column].fillna(False).astype(bool)
        return data

    def snapshot(self, bars: pd.DataFrame, symbol: str, timeframe: str, as_of: str | None = None) -> dict:
        data = self.calculate(bars, as_of)
        row = data.iloc[-1]
        direction = "BULLISH" if row.bull_strong else "BULLISH" if row.bull_bg else "BEARISH" if row.bear_bg else "NEUTRAL"
        strength = "STRONG" if row.bull_strong else "NORMAL" if row.bull_bg or row.bear_bg else "NEUTRAL"
        return {"symbol": symbol.upper(), "timeframe": timeframe, "as_of": row.date.date().isoformat(), "trend": {"direction": direction, "strength": strength, "bull_bg": bool(row.bull_bg), "bull_strong": bool(row.bull_strong), "bear_bg": bool(row.bear_bg)}, "volume": {"current": float(row.volume), "ma20": float(row.vol_ma_20), "ratio": None if pd.isna(row.volume_ratio) else float(row.volume_ratio), "vol_ok": bool(row.vol_ok), "vol_strong": bool(row.vol_strong)}, "filters": {"gap_rate": None if pd.isna(row.gap_rate) else float(row.gap_rate), "gap_ok": bool(row.gap_ok), "range_ok": bool(row.range_ok)}, "signals": {key: bool(row[key]) for key in ("b1", "b2", "b3", "s1", "s2")}, "divergence": {key: bool(row[f"{key}_raw"]) for key in ("top_1", "top_2", "top_3", "bottom_1", "bottom_2", "bottom_3")}}
