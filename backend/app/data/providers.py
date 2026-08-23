from abc import ABC, abstractmethod
from pathlib import Path
import pandas as pd
REQUIRED = ["date","open","high","low","close","volume"]
class MarketDataProvider(ABC):
    @abstractmethod
    def symbols(self) -> list[str]: ...
    @abstractmethod
    def ohlcv(self, symbol: str) -> tuple[pd.DataFrame, dict]: ...
class CsvDataProvider(MarketDataProvider):
    def __init__(self, root: Path): self.root=root; self.root.mkdir(parents=True,exist_ok=True)
    def symbols(self): return sorted(x.stem.upper() for x in self.root.glob("*.csv"))
    def ohlcv(self,symbol):
        path=self.root/f"{symbol.upper()}.csv"
        if not path.exists(): raise FileNotFoundError(symbol)
        df=pd.read_csv(path); return validate_ohlcv(df)
    def save(self,symbol,content: bytes):
        try: df=pd.read_csv(__import__('io').BytesIO(content))
        except Exception as e: raise ValueError(f"CSV读取失败：{e}")
        clean, quality=validate_ohlcv(df); path=self.root/f"{symbol.upper()}.csv"; previous=None
        if path.exists(): previous, previous_quality=self.ohlcv(symbol)
        incoming_latest=quality["end_date"]
        if previous is not None:
            previous_latest=str(previous.date.iloc[-1])
            if incoming_latest < previous_latest:
                return previous, {**previous_quality,"import_status":"REJECTED_OLDER","warning":"导入文件的最新交易日期早于当前数据，已保护现有数据。","previous_latest_bar_date":previous_latest,"incoming_latest_bar_date":incoming_latest,"new_bars":0}
            new_bars=int((pd.to_datetime(clean.date)>pd.Timestamp(previous_latest)).sum())
        else: previous_latest=None; new_bars=len(clean)
        clean.to_csv(path,index=False)
        return clean,{**quality,"import_status":"UPDATED" if new_bars else "UNCHANGED","previous_latest_bar_date":previous_latest,"latest_bar_date":incoming_latest,"new_bars":new_bars}
class FutuDataProvider(MarketDataProvider):
    def symbols(self): raise NotImplementedError("Futu 数据源尚未实现")
    def ohlcv(self,symbol): raise NotImplementedError("Futu 数据源尚未实现")
class YahooDataProvider(FutuDataProvider): pass
def validate_ohlcv(df: pd.DataFrame):
    df=df.copy(); df.columns=[str(x).strip().lower() for x in df.columns]
    missing=[x for x in REQUIRED if x not in df.columns]
    if missing: raise ValueError("CSV缺少必要列："+", ".join(missing))
    df=df[REQUIRED]; original=len(df); df["date"]=pd.to_datetime(df["date"],errors="coerce")
    for x in REQUIRED[1:]: df[x]=pd.to_numeric(df[x],errors="coerce")
    invalid=df["date"].isna()|df[REQUIRED[1:]].isna().any(axis=1)|(df[["open","high","low","close"]]<=0).any(axis=1)|(df["volume"]<0)|(df["high"]<df[["open","close","low"]].max(axis=1))|(df["low"]>df[["open","close","high"]].min(axis=1))
    missing_count=int(invalid.sum()); df=df.loc[~invalid]; duplicate_count=int(df.duplicated("date").sum()); df=df.drop_duplicates("date",keep="last").sort_values("date")
    if df.empty: raise ValueError("CSV没有可用的OHLCV记录")
    zero_volume = df["volume"].eq(0)
    zero_volume_count = int(zero_volume.sum())
    if zero_volume_count:
        groups = zero_volume.ne(zero_volume.shift()).cumsum()
        max_consecutive_zero_volume = int(zero_volume.groupby(groups).sum().max())
    else:
        max_consecutive_zero_volume = 0
    zero_volume_status = (
        "ALL_ZERO" if zero_volume_count == len(df)
        else "CONSECUTIVE" if max_consecutive_zero_volume >= 2
        else "ISOLATED" if zero_volume_count
        else "NONE"
    )
    warnings = []
    if zero_volume_status == "ALL_ZERO": warnings.append("全部记录的成交量均为零，数据不可用于量能研究。")
    elif zero_volume_status == "CONSECUTIVE": warnings.append("存在连续零成交量记录，请检查停牌、市场类型或数据源完整性。")
    elif zero_volume_status == "ISOLATED": warnings.append("存在孤立零成交量记录，请在量能研究前复核。")
    quality_label = "已清洗" if missing_count else "需复核" if warnings else "通过"
    quality={"start_date":df.date.iloc[0].date().isoformat(),"end_date":df.date.iloc[-1].date().isoformat(),"bar_count":len(df),"missing_count":missing_count,"duplicate_count":duplicate_count,"zero_volume_count":zero_volume_count,"max_consecutive_zero_volume":max_consecutive_zero_volume,"zero_volume_status":zero_volume_status,"warnings":warnings,"quality":quality_label}
    df["date"]=df.date.dt.strftime("%Y-%m-%d"); return df,quality
