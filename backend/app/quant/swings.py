import pandas as pd
def swing_points(frame: pd.DataFrame, left: int=2, right: int=2) -> pd.DataFrame:
    if left<1 or right<1: raise ValueError("Swing窗口必须大于0")
    if frame.empty: return pd.DataFrame(columns=["swing_high","swing_low"])
    if not {"high","low"}.issubset(frame.columns): raise ValueError("Swing需要 high、low 列")
    high=pd.to_numeric(frame.high,errors="coerce"); low=pd.to_numeric(frame.low,errors="coerce"); result=pd.DataFrame(index=frame.index); result["swing_high"]=False; result["swing_low"]=False
    for i in range(left,len(frame)-right):
        # Only confirm at i+right: no earlier signal uses future bars.
        result.iloc[i,result.columns.get_loc("swing_high")]=high.iloc[i]==high.iloc[i-left:i+right+1].max()
        result.iloc[i,result.columns.get_loc("swing_low")]=low.iloc[i]==low.iloc[i-left:i+right+1].min()
    return result
