"""GPMAAPRO v1: causal Python implementation of the supplied MAI formula."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.mai_language import MaiRuntime

REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}
SIGNALS = ("b01", "b02", "b03", "b11", "b12", "b3", "b4", "s01", "s02", "s11", "s12", "s2", "s22")


def _valuewhen(condition: pd.Series, value: pd.Series) -> pd.Series:
    """Causal VALUEWHEN: the latest value whose condition has occurred."""
    result: list[float] = []
    last = np.nan
    for hit, current in zip(condition.fillna(False), value, strict=True):
        if bool(hit):
            last = current
        result.append(last)
    return pd.Series(result, index=value.index, dtype="float64")


def _s01_price_reversal(
    close: pd.Series,
    open_: pd.Series,
    body: pd.Series,
    rt: MaiRuntime,
) -> tuple[pd.Series, pd.Series]:
    """Return the MAI S01 body average and its three-way price condition."""
    body_ma_20 = rt.ma(body, 20, "MA_BODY_20")
    last_bull_age = rt.barslast(close > open_, "BARSLAST_CLOSE_GT_OPEN")
    last_large_bull_age = rt.barslast(
        (close > open_) & (body > body_ma_20),
        "BARSLAST_LARGE_BULL",
    )
    last_bull_midpoint = (
        rt.ref(open_, last_bull_age, "REF_OPEN_LAST_BULL")
        + rt.ref(close, last_bull_age, "REF_CLOSE_LAST_BULL")
    ) / 2
    last_large_bull_open = rt.ref(
        open_,
        last_large_bull_age,
        "REF_OPEN_LARGE_BULL",
    )
    price_reversal = (
        (close < open_.shift(1))
        | (close < last_bull_midpoint)
        | ((close < open_) & (close < last_large_bull_open))
    )
    return body_ma_20, price_reversal


class GpmaAproEngine:
    def calculate(self, bars: pd.DataFrame, as_of: str | None = None) -> pd.DataFrame:
        if not REQUIRED_COLUMNS.issubset(bars.columns):
            raise ValueError(f"GPMAAPRO requires OHLCV columns: {', '.join(sorted(REQUIRED_COLUMNS - set(bars.columns)))}")
        data = bars.copy().sort_values("date").reset_index(drop=True)
        data["date"] = pd.to_datetime(data["date"])
        if as_of:
            data = data[data.date <= pd.Timestamp(as_of)].copy().reset_index(drop=True)
        if data.empty:
            raise ValueError("No OHLCV data is available at as_of")
        for name in REQUIRED_COLUMNS - {"date"}:
            data[name] = pd.to_numeric(data[name], errors="coerce")
        if data[list(REQUIRED_COLUMNS - {"date"})].isna().any().any():
            raise ValueError("GPMAAPRO received invalid OHLCV data")
        close, high, low, open_ = (data[name] for name in ("close", "high", "low", "open"))
        rt = MaiRuntime(data.index)
        for period in (8, 10, 12, 15, 20, 40, 45, 50, 55, 60):
            data[f"ema_{period}"] = rt.ema(close, period, f"E{period}")
        data["ma_120"] = rt.ma(close, 120, "E120"); data["ma_250"] = rt.ma(close, 250, "E250")
        data["diff"] = rt.put("DIFF", rt.ema(close, 12, "DIFF_EMA12") - rt.ema(close, 26, "DIFF_EMA26"))
        data["dea"] = rt.ema(data["diff"], 9, "DEA"); data["macd"] = rt.put("MACD", (data["diff"] - data["dea"]) * 2)
        previous_close = rt.ref(close, 1, "REF_CLOSE_1")
        tr = pd.concat([high-low, (previous_close-high).abs(), (previous_close-low).abs()], axis=1).max(axis=1)
        data["atr_26"] = rt.ma(rt.put("TR", tr), 26, "ATR")
        e = lambda n: data[f"ema_{n}"]
        body = (close-open_).abs(); body_safe = body.replace(0, np.nan)
        recent_high20 = high.eq(rt.hhv(high, 20, "HHV_HIGH_20"))
        # Source conditions retain their names so trace/reconciliation can compare them directly.
        data["b01_raw"] = (data.dea < 0) & (data.dea.shift(10) > 0) & (data.macd > data.macd.shift(1)) & (data.macd.shift(1) < data.macd.shift(2)) & (close > previous_close) & (close > open_) & (high < e(8)) & (high < e(60)) & (low.shift(1) < low.shift(10)) & low.shift(1).eq(rt.llv(low, 20, "LLV_LOW_20"))
        data["b02_raw"] = (close > open_) & (close.shift(1) < open_.shift(1)) & (close > (open_.shift(1)+close.shift(1))/2) & (data.macd > data.macd.shift(1)) & (data.dea < 0) & (data.dea.shift(10) > 0) & (high < e(8))
        data["b03_raw"] = (low < data.ma_120) & (close > data.ma_120) & ((close-low).abs()/body_safe > 1.5) & (close < e(60))
        data["b11_raw"] = (e(8)>e(10))&(e(10)>e(12))&(e(12)>e(15))&(close>open_)&(close.shift(1)<e(60))&(close>e(60))
        data["b12_raw"] = (e(20)>e(60))&(data.dea>0)&(data.dea.shift(25)<0)&(close>open_)&(data.macd>data.macd.shift(1))&(data.macd<0)&~(e(8)>e(10))
        data["b3_raw"] = (e(20)>e(60))&(data.dea>0)&(close>open_)&((open_<e(20))|(low<e(20))|(open_.shift(1)<e(20)))&(close>e(20))&~high.eq(rt.hhv(high,15,"HHV_HIGH_15"))&(data.macd>data.macd.shift(1))
        data["b4_raw"] = (e(40)>e(45))&(e(45)>e(50))&(e(50)>e(55))&(e(55)>e(60))&(e(20)>e(60))&(data.macd>data.macd.shift(1))&~high.eq(rt.hhv(high,10,"HHV_HIGH_10"))&(close>open_)&((open_<e(60))|(low<e(60))|(low.shift(1)<e(60)))&(close>e(60))
        body_ma_20, s01_price_reversal = _s01_price_reversal(close, open_, body, rt)
        recent_high_20 = pd.concat(
            [
                high.shift(i).eq(rt.hhv(high, 20, "HHV_HIGH_20_S01"))
                for i in range(5)
            ],
            axis=1,
        ).any(axis=1)
        data["s01_raw"] = (
            (data.dea > 0)
            & (data.macd > 0)
            & (data.macd < data.macd.shift(1))
            & (open_ > close)
            & (low > e(8))
            & (body > body_ma_20 * .6)
            & s01_price_reversal
            & recent_high_20
            & (data.dea.shift(5) > 0)
        )
        data["s02_raw"] = high.eq(rt.hhv(high,5,"HHV_HIGH_5"))&(data.macd<data.macd.shift(1))&(data["diff"]>0)&(data.dea.shift(10)<0)&high.eq(rt.hhv(high,10,"HHV_HIGH_10_S02"))&~((e(8)>e(10))&(e(10)>e(12))&(e(12)>e(15))&(e(15)>e(20)))
        bear_stack = (e(8)<e(10))&(e(10)<e(12))&(e(12)<e(15))&(e(15)<e(20))
        data["s11_raw"] = (((e(20)<e(60))&(e(55)<e(60)))|((e(15)<e(20))&(e(20)<e(60))))&(data.dea<0)&(data.macd>0)&(open_>close)&((close-low)/body_safe<1.5)&((open_>e(60))|(high>e(60))|(high.shift(1)>e(60)))&(close<e(60))&~low.eq(rt.llv(low,10,"LLV_LOW_10"))&~bear_stack
        data["s12_raw"] = bear_stack&(close<open_)&(close<e(8))&(close<e(60))&close.eq(rt.llv(close,10,"LLV_CLOSE_10"))&~((data.macd>data.macd.shift(1))&(data.macd.shift(1)>data.macd.shift(2)))&(data.dea.shift(10)>0)&~((low<data.ma_120)&(close>data.ma_120))
        data["s2_raw"] = (e(15)<e(20))&(e(20)<e(60))&(data.dea<0)&(data.macd>0)&(open_>close)&((open_>e(20))|(high>e(20))|(high.shift(1)>e(20)))&(close<e(20))&~low.eq(rt.llv(low,10,"LLV_LOW_10_S2"))&(data.macd<data.macd.shift(1))
        data["s22_raw"] = (e(12)<e(15))&(e(15)<e(20))&(e(20)<e(60))&(close<e(20))&(high.shift(1)>e(20))&(close<close.shift(1))&(data.dea<0)&(data.macd<data.macd.shift(1))&~close.eq(rt.llv(close,10,"LLV_CLOSE_10_S22"))
        # Formula drawing guards: COUNT includes the current bar.
        count = lambda key, window: rt.count(data[f"{key}_raw"], window, f"COUNT_{key.upper()}_{window}")
        data["b01"] = data.b01_raw&(count("b01",5)<2)&(count("b02",5)<1)
        data["b02"] = data.b02_raw&(count("b02",5)<2); data["b03"] = data.b03_raw&(count("b03",5)<2)&(count("b01",5)<1)&(count("b02",5)<1)
        data["b11"] = data.b11_raw&(count("b11",5)<2)&(count("b4",5)<1); data["b12"] = data.b12_raw&(count("b12",5)<2)&(count("b4",5)<1)
        data["b3"] = data.b3_raw&(count("b3",5)<2)&(count("b12",5)<1)&(count("b4",5)<1); data["b4"] = data.b4_raw&(count("b4",5)<2)&(count("b02",5)<1)&((count("b4",5)<2)|(count("s12",5)>=1))
        data["s01"] = data.s01_raw&(count("s01",5)<2); data["s02"] = data.s02_raw&(count("s02",5)<2)
        data["s11"] = data.s11_raw&(count("s11",5)<2)&(count("s12",6)<1)&(count("s2",6)<1)
        data["s12"] = data.s12_raw&(count("s12",6)<2)&(count("s2",5)<1)&(count("s11",6)<2)&(count("s22",5)<1)
        data["s2"] = data.s2_raw&(count("s2",5)<2)&(count("s12",5)<1); data["s22"] = data.s22_raw&(count("s2",5)<1)&(count("s22",5)<2)
        jc=rt.cross(data["diff"],data["dea"],"JC"); sc=(data["diff"]<data["dea"])&(data["diff"].shift(1)>=data["dea"].shift(1)); n1=rt.barslast(jc.shift(1,fill_value=False),"BARSLAST_REF_JC")+1; n2=rt.barslast(sc.shift(1,fill_value=False),"BARSLAST_REF_SC")+1
        hh=_valuewhen(sc,rt.hhv(high,n1,"HHV_H_N1")); mhd=_valuewhen(sc,rt.hhv(data.macd,n1,"HHV_MACD_N1")); ll=_valuewhen(jc,rt.llv(low,n2,"LLV_L_N2")); mld=_valuewhen(jc,rt.llv(data.macd,n2,"LLV_MACD_N2"))
        peak=(data.macd.shift(1)>data.macd.shift(2))&(data.macd.shift(1)>data.macd); trough=(data.macd.shift(1)<data.macd.shift(2))&(data.macd.shift(1)<data.macd)
        tbl1=peak&(data.macd>0)&(_valuewhen(peak,high.shift(1))>hh)&(_valuewhen(peak,data.macd.shift(1))<mhd); bbl1=trough&(data.macd<0)&(_valuewhen(trough,low.shift(1))<ll)&(_valuewhen(trough,data.macd.shift(1))>mld)&(high<e(20))
        tbl2=(data.dea>0)&(high>rt.ref(rt.hhv(high,10,"HHV_H_10"),2,"KH"))&(data.macd<rt.ref(rt.hhv(data.macd,10,"HHV_MACD_10"),2,"MACDH"))&(data.macd<data.macd.shift(1))&((close-open_).shift(1)>0)&(low>e(8))&(open_>close)
        bbl2=(data.dea<0)&(low<rt.ref(rt.llv(low,10,"LLV_L_10"),2,"KL"))&(data.macd>rt.ref(rt.llv(data.macd,10,"LLV_MACD_10"),2,"MACDL"))&(data.macd>data.macd.shift(1))&((close-open_).shift(1)<0)&(high<e(8))&(open_<close)
        data["top_1"],data["bottom_1"],data["top_2"],data["bottom_2"]=tbl1,bbl1,tbl2,bbl2
        for key in SIGNALS: data[f"{key}_label_y"]=(low-.5*data.atr_26).where(data[key])
        data["top_1_y"]=(close+1.5*data.atr_26).where(tbl1&(rt.count(tbl1,5,"COUNT_TBL1_5")<2)&(close>e(10))&(close<open_)); data["bottom_1_y"]=(close-1.5*data.atr_26).where(bbl1&(rt.count(bbl1,5,"COUNT_BBL1_5")<2)&(close<e(10))&(close>open_)); data["top_2_y"]=(open_+.3*data.atr_26).where(tbl2&(rt.count(tbl2,5,"COUNT_TBL2_5")<2)); data["bottom_2_y"]=(low-.3*data.atr_26).where(bbl2&(rt.count(bbl2,5,"COUNT_BBL2_5")<2))
        for name, value in rt.trace.items():
            if name not in data: data[name]=value
        for key in [*SIGNALS, *[f"{x}_raw" for x in SIGNALS], "top_1", "bottom_1", "top_2", "bottom_2"]: data[key]=data[key].fillna(False).astype(bool)
        return data
