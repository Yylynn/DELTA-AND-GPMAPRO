import pandas as pd
REQUIRED={"high","low","close"}
def _empty(series_name: str) -> pd.Series: return pd.Series(dtype="float64",name=series_name)
def wilder_atr(frame: pd.DataFrame, period: int=14) -> pd.Series:
    if period<1: raise ValueError("ATR周期必须大于0")
    if frame.empty: return _empty("atr")
    if not REQUIRED.issubset(frame.columns): raise ValueError("ATR需要 high、low、close 列")
    high=pd.to_numeric(frame.high,errors="coerce"); low=pd.to_numeric(frame.low,errors="coerce"); close=pd.to_numeric(frame.close,errors="coerce")
    tr=pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/period,adjust=False,min_periods=period).mean(); atr.name="atr"; return atr
def ema(frame: pd.DataFrame, period: int) -> pd.Series:
    if period<1: raise ValueError("EMA周期必须大于0")
    if frame.empty: return _empty(f"ema_{period}")
    if "close" not in frame: raise ValueError("EMA需要 close 列")
    out=pd.to_numeric(frame.close,errors="coerce").ewm(span=period,adjust=False,min_periods=period).mean(); out.name=f"ema_{period}"; return out
def ema_50_200(frame: pd.DataFrame) -> pd.DataFrame: return pd.DataFrame({"ema50":ema(frame,50),"ema200":ema(frame,200)})
