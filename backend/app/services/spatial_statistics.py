from dataclasses import dataclass
import numpy as np
import pandas as pd
@dataclass
class SpatialStatisticsService:
    windows: tuple[int,...]=(5,10,20,40)
    insufficient_sample_threshold: int = 20
    low_sample_threshold: int = 50
    medium_sample_threshold: int = 100

    def sample_quality(self, count: int) -> str:
        if count < self.insufficient_sample_threshold: return "INSUFFICIENT"
        if count < self.low_sample_threshold: return "LOW"
        if count < self.medium_sample_threshold: return "MEDIUM"
        return "GOOD"
    def analyze(self, bars:pd.DataFrame, events:list[dict], observation_days:int, train_end:str|pd.Timestamp)->dict:
        if observation_days not in self.windows: raise ValueError("观察窗口仅支持 5、10、20、40 个交易日")
        required={"date","high","low","close","atr"}
        if not required.issubset(bars.columns): raise ValueError("行情需要 date、high、low、close、atr 列")
        data=bars.copy();data.date=pd.to_datetime(data.date);cutoff=pd.to_datetime(train_end); data=data.sort_values("date").reset_index(drop=True)
        samples=[]
        for event in events:
            event_date=pd.to_datetime(event["expected_date"])
            if event_date>cutoff: continue
            hits=data.index[data.date==event_date]
            if not len(hits): continue
            i=int(hits[0]); end=i+observation_days
            if end>=len(data) or data.date.iloc[end]>cutoff: continue
            entry=float(data.close.iloc[i]);atr=float(data.atr.iloc[i])
            if not np.isfinite(atr) or atr<=0: continue
            future=data.iloc[i+1:end+1]
            if event["event_type"]=="LOW": mfe=(future.high.max()-entry)/atr; mae=(entry-future.low.min())/atr
            else: mfe=(entry-future.low.min())/atr; mae=(future.high.max()-entry)/atr
            samples.append({"event_id":event["event_id"],"event_type":event["event_type"],"event_date":event_date.date().isoformat(),"entry":entry,"atr":atr,"mfe_atr":float(mfe),"mae_atr":float(mae),"mfe_pct":float(mfe*atr/entry*100),"mae_pct":float(mae*atr/entry*100)})
        def stats(key):
            v=np.array([x[key] for x in samples],dtype=float)
            if not len(v): return {"mean":None,"median":None,"p25":None,"p50":None,"p70":None,"p85":None,"p90":None}
            return {"mean":float(v.mean()),"median":float(np.median(v)),**{f"p{p}":float(np.percentile(v,p)) for p in (25,50,70,85,90)}}
        count = len(samples)
        return {"observation_days":observation_days,"train_end":cutoff.date().isoformat(),"sample_count":count,"sample_quality":self.sample_quality(count),"mfe":stats("mfe_atr"),"mae":stats("mae_atr"),"samples":samples}
    def targets(self, statistics:dict, event_type:str, entry:float, atr:float)->dict:
        m=statistics["mfe"]; sign=1 if event_type=="LOW" else -1
        return {"t1":entry+sign*m["p50"]*atr,"t2":entry+sign*m["p70"]*atr,"t3":entry+sign*m["p85"]*atr,"expected_mae_atr":statistics["mae"]["p50"]}
