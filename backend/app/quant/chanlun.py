"""Simplified Chanlun structure analysis migrated from financial_terminal.

This module deliberately preserves the source project's contained-candle,
fractals, strokes, central zones, and simplified buy/sell-point definitions.
It is a research structure extractor, not a trading-signal engine.
"""

import pandas as pd


def _merge_contains(df: pd.DataFrame) -> list[dict]:
    rows = df.reset_index(drop=True)
    if rows.empty:
        return []
    merged: list[dict] = []
    direction = 0

    def merge_two(left: dict, right: dict) -> dict:
        high = max(left["high"], right["high"]) if direction >= 0 else min(left["high"], right["high"])
        low = max(left["low"], right["low"]) if direction >= 0 else min(left["low"], right["low"])
        return {"open": left["open"], "close": right["close"], "high": high, "low": low, "index": right["index"]}

    current = {key: float(rows.iloc[0][key]) for key in ("open", "high", "low", "close")}
    current["index"] = 0
    for index in range(1, len(rows)):
        row = rows.iloc[index]
        nxt = {key: float(row[key]) for key in ("open", "high", "low", "close")}
        nxt["index"] = index
        contains = (current["high"] >= nxt["high"] and current["low"] <= nxt["low"]) or (nxt["high"] >= current["high"] and nxt["low"] <= current["low"])
        if contains:
            current = merge_two(current, nxt)
        else:
            merged.append(current)
            if nxt["high"] > current["high"]:
                direction = 1
            elif nxt["low"] < current["low"]:
                direction = -1
            current = nxt
    merged.append(current)
    return merged


def _identify_fractals(merged: list[dict]) -> list[tuple[str, int]]:
    fractals: list[tuple[str, int]] = []
    for index in range(1, len(merged) - 1):
        previous, current, nxt = merged[index - 1], merged[index], merged[index + 1]
        if current["high"] > previous["high"] and current["high"] > nxt["high"] and current["low"] > previous["low"] and current["low"] > nxt["low"]:
            fractals.append(("top", current["index"]))
        elif current["low"] < previous["low"] and current["low"] < nxt["low"] and current["high"] < previous["high"] and current["high"] < nxt["high"]:
            fractals.append(("bottom", current["index"]))
    return fractals


def _identify_bi(fractals: list[tuple[str, int]], df: pd.DataFrame) -> list[dict]:
    bis: list[dict] = []
    cursor = 0
    while cursor < len(fractals) - 1:
        first_kind, first_index = fractals[cursor]
        target = cursor + 1
        while target < len(fractals) and fractals[target][0] == first_kind:
            target += 1
        if target >= len(fractals):
            break
        second_kind, second_index = fractals[target]
        if second_index - first_index < 2:
            cursor = target
            continue
        first = df.iloc[first_index]
        second = df.iloc[second_index]
        bis.append({
            "kind": first_kind,
            "start_idx": int(first_index), "end_idx": int(second_index),
            "start_price": round(float(first["high"] if first_kind == "top" else first["low"]), 2),
            "end_price": round(float(second["low"] if second_kind == "bottom" else second["high"]), 2),
            "direction": "down" if first_kind == "top" else "up",
        })
        cursor = target
    return bis


def _identify_zhongshu(bis: list[dict]) -> list[dict]:
    zones: list[dict] = []
    for index in range(len(bis) - 2):
        segment = bis[index:index + 3]
        zg = min(max(item["start_price"], item["end_price"]) for item in segment)
        zd = max(min(item["start_price"], item["end_price"]) for item in segment)
        if zg > zd:
            zone = {"zg": round(zg, 2), "zd": round(zd, 2), "start_idx": segment[0]["start_idx"], "end_idx": segment[-1]["end_idx"]}
            if zones and abs(zone["zg"] - zones[-1]["zg"]) <= 1e-6 and abs(zone["zd"] - zones[-1]["zd"]) <= 1e-6:
                zones[-1]["end_idx"] = zone["end_idx"]
            else:
                zones.append(zone)
    return zones


def _identify_buy_sell_points(bis: list[dict], zones: list[dict]) -> dict:
    buy = sell = None
    if not zones:
        if bis:
            last = bis[-1]
            if last["direction"] == "up":
                buy = {"type": "笔转折", "price": last["start_price"], "idx": last["start_idx"]}
            else:
                sell = {"type": "笔转折", "price": last["start_price"], "idx": last["start_idx"]}
        return {"buy": buy, "sell": sell}
    zone = zones[-1]
    for index in range(1, len(bis)):
        previous, current = bis[index - 1], bis[index]
        if previous["direction"] == "down" and current["direction"] == "up":
            low = current["start_price"]
            if low <= zone["zd"] * 1.03:
                buy = {"type": "一类买点" if low <= zone["zd"] else "三类买点", "price": round(low, 2), "idx": current["start_idx"]}
        elif previous["direction"] == "up" and current["direction"] == "down":
            high = current["start_price"]
            if high >= zone["zg"] * 0.97:
                sell = {"type": "一类卖点" if high >= zone["zg"] else "三类卖点", "price": round(high, 2), "idx": current["start_idx"]}
    return {"buy": buy, "sell": sell}


def chanlun_analyze(df: pd.DataFrame) -> dict:
    required = {"open", "high", "low", "close"}
    if df is None or df.empty:
        return {"status": "INSUFFICIENT_DATA", "error": "无 K 线数据", "conclusion": "无法进行缠论分析（无数据）"}
    if not required.issubset(df.columns):
        return {"status": "INVALID_DATA", "error": f"缺少必要列，需包含 {required}", "conclusion": "无法进行缠论分析（字段缺失）"}
    numeric = df.loc[:, ["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or (numeric["high"] < numeric["low"]).any():
        return {"status": "INVALID_DATA", "error": "OHLC 数据包含无效数值", "conclusion": "无法进行缠论分析（OHLC 异常）"}
    data = df.reset_index(drop=True).copy()
    data.loc[:, numeric.columns] = numeric
    if len(data) < 3:
        return {"status": "INSUFFICIENT_DATA", "error": "至少需要 3 根日线 K 线", "conclusion": "数据不足以识别分型"}
    merged = _merge_contains(data)
    fractals = _identify_fractals(merged)
    bis = _identify_bi(fractals, data)
    zones = _identify_zhongshu(bis)
    points = _identify_buy_sell_points(bis, zones)
    latest_bi = bis[-1] if bis else None
    parts: list[str] = []
    if latest_bi:
        parts.append(f"当前处于{'上升' if latest_bi['direction'] == 'up' else '下降'}笔（{latest_bi['start_price']}→{latest_bi['end_price']}）")
    if zones:
        parts.append(f"最近中枢区间 [{zones[-1]['zd']}, {zones[-1]['zg']}]")
    if points["buy"]:
        parts.append(f"最近买点：{points['buy']['type']}（{points['buy']['price']}）")
    if points["sell"]:
        parts.append(f"最近卖点：{points['sell']['type']}（{points['sell']['price']}）")
    return {
        "status": "AVAILABLE", "merged_count": len(merged),
        "fractals": [{"kind": kind, "idx": index} for kind, index in fractals],
        "bis": bis, "zhongshus": zones, "points": points, "latest_bi": latest_bi,
        "last_close": round(float(data.iloc[-1]["close"]), 2),
        "conclusion": "；".join(parts) if parts else "数据不足以形成有效笔/中枢",
    }
