import pandas as pd


def market_regime(frame: pd.DataFrame) -> dict[str, str]:
    if frame.empty or not {"close", "ema50", "ema200"}.issubset(frame.columns):
        return {"regime": "Neutral", "label": "震荡"}
    row = frame.iloc[-1]
    if pd.isna(row.close) or pd.isna(row.ema50) or pd.isna(row.ema200):
        return {"regime": "Neutral", "label": "震荡"}
    if row.ema50 > row.ema200 and row.close > row.ema200:
        return {"regime": "Bullish", "label": "多头"}
    if row.ema50 < row.ema200 and row.close < row.ema200:
        return {"regime": "Bearish", "label": "空头"}
    return {"regime": "Neutral", "label": "震荡"}
