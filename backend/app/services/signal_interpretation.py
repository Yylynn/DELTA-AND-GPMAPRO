"""Point-in-time DELTA × GPMA research interpretation; never an order engine."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from app.quant.delta_time import ITDConfig, ITDDeltaEngine
from app.services.data_freshness import freshness_snapshot
from app.services.gpmaapro_engine import GpmaAproEngine, SIGNALS as GPMA2_SIGNALS
from app.services.gpmapro_engine import GpmaProEngine
from app.services.news_advice import ACTION_GUIDANCE, ACTION_LABEL, apply_news_overlay


RECENT_BARS = 5
DELTA_ACTION_WINDOW_BARS = 10
ACTION_RULE_VERSION = "DELTA_DUAL_GPMA_LONG_ONLY_V3"
GPMA1_BULLISH = ("b1", "b2", "b3")
GPMA1_BEARISH = ("s1", "s2")
GPMA2_BULLISH = tuple(name for name in GPMA2_SIGNALS if name.startswith("b"))
GPMA2_BEARISH = tuple(name for name in GPMA2_SIGNALS if name.startswith("s"))

# Formula names alone are not useful to a discretionary user.  These are
# intentionally short, auditable descriptions of the completed GPMA2 nodes;
# they describe technical context rather than making a price prediction.
GPMA2_SIGNAL_GUIDE = {
    "B01": ("低位动能开始修复，但价格仍在短中期均线下方。", "观察性买点，等待趋势确认。"),
    "B02": ("超跌后出现转强尝试，尚未证明趋势已经反转。", "观察或小幅试探，不直接升级买入。"),
    "B03": ("下跌动能减弱，价格尝试从低位回升。", "观察性买点，需 DELTA LOW 或稳定版确认。"),
    "B11": ("价格重新站回短期均线，反弹结构开始形成。", "适当买入候选，需避免与 DELTA HIGH 冲突。"),
    "B12": ("趋势修复后出现进一步走强，均线关系改善。", "适当买入候选，等待成交量与趋势确认。"),
    "B3": ("价格在均线带附近企稳，回调后重新尝试上行。", "适当买入候选，需 DELTA LOW 或稳定版确认。"),
    "B4": ("价格重新获得短期均线支持，属于趋势延续尝试。", "观察性加仓线索，不单独触发行等级。"),
    "S01": ("高位动能开始衰减，MACD 仍为正但已走弱，并出现转弱 K 线。", "适当卖出；有 DELTA HIGH 时优先减仓，避免追高。"),
    "S02": ("股价创新高但 MACD 没有同步增强，上涨动力跟不上。", "观望并提示减仓预警，不单独卖出。"),
    "S11": ("弱势趋势中的反弹受 E60 附近压制后失败。", "适当卖出；空头趋势下提高风险等级。"),
    "S12": ("均线空头排列，跌破关键均线并创近 10 日低点。", "卖出候选；需稳定版或已对账确认才显示卖出。"),
    "S2": ("反弹到 E20 附近再次失败，MACD 动力继续减弱。", "适当卖出；连续出现或趋势转空时升级卖出候选。"),
    "S22": ("空头排列中反抽失败后继续走弱，MACD 继续恶化。", "卖出候选；与 DELTA HIGH 或稳定版 S 同向时增强。"),
}


def _guide_detail(source: str, code: str, signal: dict, *, symbol: str, trend: str, delta: dict, source_status: str) -> dict:
    plain, impact = GPMA2_SIGNAL_GUIDE.get(code, ("指标在当前 K 线给出技术性确认。", "作为辅助证据，需结合趋势与 DELTA 判断。"))
    delta_bits = [f"DELTA {event['event_type']} 可交易日 {event['tradable_on']}" for event in delta["active_windows"]]
    context = f"{symbol} 当前趋势 {trend}；" + ("；".join(delta_bits) if delta_bits else "当前无 DELTA 行动窗口。")
    return {"source": source, "signal_code": code, "date": signal["date"], "plain_language": plain, "market_context": context, "action_impact": impact, "confidence": "已对账" if source_status == "AVAILABLE" else "研究级，待富途逐 bar 绘图对账", "why_now": f"{code} 于 {signal['date']} 触发，距当前 {signal['bars_since']} 根 K 线。", "what_invalidates_it": "出现同级反向最终 B/S 信号，或价格与趋势重新恢复到相反方向。"}


def _recent_hits(data: pd.DataFrame, names: Iterable[str]) -> list[dict]:
    result: list[dict] = []
    for name in names:
        hits = data.index[data[name].fillna(False).astype(bool)].tolist()
        if hits:
            index = hits[-1]
            age = len(data) - 1 - index
            if age <= RECENT_BARS:
                result.append({"code": name.upper(), "date": data.date.iloc[index].date().isoformat(), "bars_since": age, "active": age == 0})
    return result


def _recent_divergences(data: pd.DataFrame, mapping: dict[str, tuple[str, str]]) -> list[dict]:
    result: list[dict] = []
    for field, (code, direction) in mapping.items():
        hits = data.index[data[field].fillna(False).astype(bool)].tolist()
        if hits:
            index = hits[-1]
            age = len(data) - 1 - index
            if age <= RECENT_BARS:
                result.append({"code": code, "direction": direction, "date": data.date.iloc[index].date().isoformat(), "bars_since": age, "active": age == 0})
    return result


def _indicator_summary(name: str, data: pd.DataFrame, bullish: Iterable[str], bearish: Iterable[str], divergence: dict[str, tuple[str, str]], *, source_status: str = "AVAILABLE", script_sha256: str | None = None) -> dict:
    bull = _recent_hits(data, bullish)
    bear = _recent_hits(data, bearish)
    divergences = _recent_divergences(data, divergence)
    bull_div = [item for item in divergences if item["direction"] == "BULLISH"]
    bear_div = [item for item in divergences if item["direction"] == "BEARISH"]
    latest = data.iloc[-1]
    # Both formula versions use the GMMA 20/60 relationship as a concise
    # trend context. Final B/S signals remain separate evidence.
    trend = "BULLISH" if float(latest.ema_20) > float(latest.ema_60) else "BEARISH" if float(latest.ema_20) < float(latest.ema_60) else "NEUTRAL"
    direction = "CONFLICT" if (bull or bull_div) and (bear or bear_div) else "BULLISH" if (bull or bull_div) else "BEARISH" if (bear or bear_div) else "NEUTRAL"
    return {
        "indicator": name,
        "source_status": source_status,
        "script_sha256": script_sha256,
        "trend": trend,
        "direction": direction,
        "bullish_signals": bull,
        "bearish_signals": bear,
        "bullish_divergences": bull_div,
        "bearish_divergences": bear_div,
        "has_bullish_confirmation": bool(bull or bull_div),
        "has_bearish_confirmation": bool(bear or bear_div),
    }


class SignalInterpretationService:
    def __init__(self, news_advice=None):
        self.gpma1, self.gpma2 = GpmaProEngine(), GpmaAproEngine()
        self.news_advice = news_advice

    @staticmethod
    def _delta(data: pd.DataFrame) -> dict:
        config_path = Path(__file__).resolve().parents[3] / "data" / "itd_config.json"
        config = ITDConfig.model_validate(json.loads(config_path.read_text(encoding="utf-8"))) if config_path.exists() else ITDConfig()
        analysis = ITDDeltaEngine(config).analyze(data)
        as_of = data.date.iloc[-1].date()
        active: list[dict] = []
        for point in analysis.get("confirmed_points", []):
            tradable = point.get("tradable_on")
            if not tradable or pd.Timestamp(tradable).date() > as_of:
                continue
            # A DELTA extreme is informative on its actual date, but actionable
            # only after confirmation.  The action window must therefore start
            # at tradable_on; using the extreme date silently discards delayed
            # confirmations during historical replay.
            index = data.index[data.date.dt.date >= pd.Timestamp(tradable).date()].tolist()
            if not index:
                continue
            bars_since = len(data) - 1 - index[0]
            if bars_since <= DELTA_ACTION_WINDOW_BARS:
                event_type = point["type"]
                end_index = min(index[0] + DELTA_ACTION_WINDOW_BARS, len(data) - 1)
                active.append({"event_id": point["id"], "event_type": event_type, "direction": "BULLISH" if event_type == "LOW" else "BEARISH", "actual_date": point["actual_date"], "confirmed_on": point["confirmed_on"], "tradable_on": tradable, "delta_window_start": data.date.iloc[index[0]].date().isoformat(), "delta_window_end": data.date.iloc[end_index].date().isoformat(), "bars_since": bars_since, "action_eligible": True, "active": bars_since == 0})
        directions = {item["direction"] for item in active}
        return {"status": analysis.get("status"), "active_windows": active, "direction": "CONFLICT" if len(directions) > 1 else next(iter(directions), "NEUTRAL"), "reversal_state": analysis.get("reversal", {}).get("state", "NORMAL")}

    @staticmethod
    def _gpma2_authority(data: pd.DataFrame, symbol: str, timeframe: str) -> tuple[str, str | None]:
        """Report local GPMA2 provenance without touching OpenD at request time.

        Futu reconciliation is an explicit offline workflow.  A missing OpenD
        process must never block the current action recommendation.
        """
        if timeframe != "1d":
            return "UNAVAILABLE", None
        return "LOCAL_RENDERER_FALLBACK", None

    def interpret(self, bars: pd.DataFrame, symbol: str, timeframe: str, source: dict, as_of: str | None = None, *, _authority: tuple[str, str | None] | None = None, _include_audit: bool = True, _include_news: bool = True, _skip_gpma2: bool = False, _precomputed_gpma1: pd.DataFrame | None = None, _precomputed_gpma2: pd.DataFrame | None = None) -> dict:
        data = bars.copy().sort_values("date").reset_index(drop=True)
        data["date"] = pd.to_datetime(data["date"])
        if as_of:
            data = data[data.date <= pd.Timestamp(as_of)].copy().reset_index(drop=True)
        if data.empty:
            raise ValueError("No OHLCV data is available at as_of")
        delta = self._delta(data)
        # Both GPMA engines are causal (rolling/REF only).  During the 30-day
        # audit we may therefore slice a full-snapshot computation safely while
        # still recomputing DELTA confirmation at each historical cutoff.
        gpma1_data = (_precomputed_gpma1[_precomputed_gpma1.date <= data.date.iloc[-1]].copy().reset_index(drop=True) if _precomputed_gpma1 is not None else self.gpma1.calculate(data))
        gpma1 = _indicator_summary("GPMAPRO", gpma1_data, GPMA1_BULLISH, GPMA1_BEARISH, {"bottom_face": ("BOTTOM_FACE", "BULLISH"), "bottom_2": ("BOTTOM_ARROW_2", "BULLISH"), "bottom_3": ("BOTTOM_ARROW_3", "BULLISH"), "top_face": ("TOP_FACE", "BEARISH"), "top_2": ("TOP_ARROW_2", "BEARISH"), "top_3": ("TOP_ARROW_3", "BEARISH")})
        status, script_hash = _authority or self._gpma2_authority(data, symbol, timeframe)
        gpma2_data = None if _skip_gpma2 else (_precomputed_gpma2[_precomputed_gpma2.date <= data.date.iloc[-1]].copy().reset_index(drop=True) if _precomputed_gpma2 is not None else self.gpma2.calculate(data))
        gpma2 = ({"indicator": "GPMA2", "source_status": status, "script_sha256": script_hash, "trend": "NEUTRAL", "direction": "NEUTRAL", "bullish_signals": [], "bearish_signals": [], "bullish_divergences": [], "bearish_divergences": [], "has_bullish_confirmation": False, "has_bearish_confirmation": False} if _skip_gpma2 else _indicator_summary("GPMA2", gpma2_data, GPMA2_BULLISH, GPMA2_BEARISH, {"bottom_1": ("BOTTOM_FACE", "BULLISH"), "bottom_2": ("BOTTOM_ARROW_2", "BULLISH"), "top_1": ("TOP_FACE", "BEARISH"), "top_2": ("TOP_ARROW_2", "BEARISH")}, source_status=status, script_sha256=script_hash))
        indicators = [gpma1, gpma2]
        # A fallback drawing cannot produce BUY/SELL.  It can nevertheless
        # request a research-grade REDUCE/ACCUMULATE with its provenance shown.
        gpma2_is_authoritative = gpma2["source_status"] == "AVAILABLE"
        # B/S are the action triggers. Divergences remain visible risk/context
        # evidence, but do not indefinitely veto a newer final B/S signal.
        actionable_bullish = bool(gpma1["bullish_signals"])
        actionable_bearish = bool(gpma1["bearish_signals"])
        delta_direction = delta["direction"]
        conflict_reasons: list[str] = []
        if delta_direction == "CONFLICT" or (actionable_bullish and actionable_bearish): conflict_reasons.append("同一观察期存在相反方向的 DELTA 或稳定 GPMAPRO 最终 B/S 信号。")
        if delta_direction == "BULLISH" and actionable_bearish: conflict_reasons.append("DELTA LOW 窗口内出现稳定 GPMAPRO 看空证据。")
        if delta_direction == "BEARISH" and actionable_bullish: conflict_reasons.append("DELTA HIGH 窗口内出现稳定 GPMAPRO 看多证据。")
        if gpma2_is_authoritative and gpma1["direction"] not in {"NEUTRAL", gpma2["direction"]} and gpma2["direction"] != "NEUTRAL": conflict_reasons.append("已对账的 GPMAPRO 与 GPMA2 近期最终信号方向不一致。")
        reference_date = data.date.iloc[-1].date() if as_of else date.today()
        stale = freshness_snapshot(data.date.iloc[-1].date(), len(data), reference_date)["freshness"] in {"STALE", "VERY_STALE", "UNKNOWN"}
        if stale: conflict_reasons.append("行情快照不是当前数据，不能形成新的研究候选。")
        long_confirmed = delta_direction == "BULLISH" and actionable_bullish
        short_confirmed = delta_direction == "BEARISH" and actionable_bearish
        if conflict_reasons:
            state, direction = "CONFLICT", "NEUTRAL"
        elif long_confirmed:
            state, direction = "POTENTIAL_LONG", "BULLISH"
        elif short_confirmed:
            state, direction = "POTENTIAL_SHORT", "BEARISH"
        elif delta_direction != "NEUTRAL" or actionable_bullish or actionable_bearish:
            state, direction = "WATCH", delta_direction if delta_direction != "NEUTRAL" else ("BULLISH" if actionable_bullish else "BEARISH")
        else:
            state, direction = "NO_SETUP", "NEUTRAL"
        missing: list[str] = []
        if delta_direction == "NEUTRAL": missing.append("尚无最近且已确认、已生效的 DELTA LOW/HIGH 结构点。")
        if direction == "BULLISH" and not actionable_bullish: missing.append("等待稳定 GPMAPRO 的最终 B 信号或底部背离确认。")
        if direction == "BEARISH" and not actionable_bearish: missing.append("等待稳定 GPMAPRO 的最终 S 信号或顶部背离确认。")
        if gpma2["source_status"] != "AVAILABLE": missing.append("GPMA2 最终绘图目前为本地等价重建，尚未完成富途逐 bar 绘图对账。")
        evidence = []
        for event in delta["active_windows"]:
            evidence.append({"source": "DELTA", "direction": event["direction"], "label": f"已确认 DELTA {event['event_type']}", "date": event["actual_date"], "detail": f"确认 {event['confirmed_on']}；可交易 {event['tradable_on']}"})
        for indicator in indicators:
            for signal in [*indicator["bullish_signals"], *indicator["bearish_signals"], *indicator["bullish_divergences"], *indicator["bearish_divergences"]]:
                evidence.append({"source": indicator["indicator"], "direction": "BULLISH" if signal["code"].startswith(("B", "BOTTOM")) else "BEARISH", "label": signal["code"], "date": signal["date"], "detail": f"{signal['bars_since']} bars 前"})
        summary = "当前没有可组合的 DELTA 与最终 GPMA 信号。" if state == "NO_SETUP" else "DELTA 与指标存在方向冲突，等待新的确认。" if state == "CONFLICT" else "存在潜在做多研究候选；仍需结合趋势、成交量和风险管理。" if state == "POTENTIAL_LONG" else "存在潜在做空/风险回避研究候选；仍需结合趋势、成交量和风险管理。" if state == "POTENTIAL_SHORT" else "已有单侧证据，但组合条件尚未齐备，继续观察。"
        latest = gpma1_data.iloc[-1]
        stable_bull = actionable_bullish
        stable_bear = actionable_bearish
        trend_bearish = gpma1["trend"] == "BEARISH"
        trend_non_bearish = not trend_bearish
        volume_confirmed = bool(latest.get("vol_ok", False))
        buy_filters = bool(latest.get("gap_ok", True)) and bool(latest.get("range_ok", True))
        verified_gpma2_agrees = gpma2["source_status"] == "AVAILABLE" and gpma2["direction"] == "BULLISH" and gpma1["direction"] in {"BULLISH", "NEUTRAL"}
        gpma2_codes = {item["code"] for item in [*gpma2["bullish_signals"], *gpma2["bearish_signals"]]}
        delta_has_high = any(event["event_type"] == "HIGH" for event in delta["active_windows"])
        delta_has_low = any(event["event_type"] == "LOW" for event in delta["active_windows"])
        fallback_gpma2 = gpma2["source_status"] == "LOCAL_RENDERER_FALLBACK"
        fallback_reduce = fallback_gpma2 and not stable_bull and bool(gpma2_codes & {"S01", "S11", "S2", "S12", "S22"}) and (delta_has_high or trend_bearish or bool(gpma2_codes & {"S12", "S22"}))
        fallback_accumulate = fallback_gpma2 and not stable_bear and bool(gpma2_codes & {"B11", "B12", "B3"}) and delta_has_low and not delta_has_high
        blocked_by: list[str] = []
        action, action_label, action_strength, position_guidance = "HOLD", "观望", 30, "不新增多头；已有持仓继续观察。"
        next_steps = ["等待已确认 DELTA LOW/HIGH 与稳定 GPMAPRO 最终信号形成同向组合。"]
        if not stale and not conflict_reasons and delta_direction == "BULLISH" and stable_bull:
            if trend_non_bearish and volume_confirmed and buy_filters:
                action, action_label, action_strength, position_guidance = "BUY", "买入", 82 if verified_gpma2_agrees else 74, "可建立多头研究仓位；不代表自动下单。"
                next_steps = ["若趋势或成交量转弱，降级为观望。", "GPMA2 完成富途绘图对账后，可作为额外确认。"]
            else:
                action, action_label, action_strength, position_guidance = "ACCUMULATE", "适当买入", 58, "可小幅增加多头暴露；等待趋势与成交量进一步确认。"
                next_steps = ["等待 GPMAPRO 趋势保持非空头且成交量确认，再升级为买入。"]
                if trend_bearish: blocked_by.append("稳定 GPMAPRO 趋势仍为空头。")
                if not volume_confirmed: blocked_by.append("成交量确认尚未通过。")
                if not buy_filters: blocked_by.append("跳空或波动过滤尚未通过。")
        elif not stale and not conflict_reasons and delta_direction == "BEARISH" and stable_bear:
            if trend_bearish:
                action, action_label, action_strength, position_guidance = "SELL", "卖出", 80, "已有多头以清仓为优先；不建立空头。"
                next_steps = ["等待新的已确认 DELTA LOW 与稳定 GPMAPRO B 信号后，才重新评估多头。"]
            else:
                action, action_label, action_strength, position_guidance = "REDUCE", "适当卖出", 58, "已有多头考虑减仓；趋势尚未完全转空。"
                next_steps = ["若 GPMAPRO 转为空头趋势且 S 信号仍有效，则升级为卖出。"]
        elif not stale and not conflict_reasons and stable_bull and verified_gpma2_agrees:
            action, action_label, action_strength, position_guidance = "ACCUMULATE", "适当买入", 52, "两版指标同向，但尚无近期已确认 DELTA LOW；仅适合小幅增加多头暴露。"
            next_steps = ["等待已确认 DELTA LOW 后，再评估是否升级为买入。"]
        elif not stale and fallback_reduce:
            action, action_label, action_strength, position_guidance = "REDUCE", "适当卖出", 46, "GPMA2 给出研究级减仓信号；减仓而非清仓，等待稳定版或富途对账确认。"
            next_steps = ["若稳定 GPMAPRO 出现最终 S 信号或 GPMA2 完成富途对账，才评估升级为卖出。"]
            if delta_has_low:
                blocked_by.append("同日存在反向 DELTA LOW；保留减仓结论，但需防范快速反弹。")
            if conflict_reasons:
                blocked_by.extend(reason for reason in conflict_reasons if "DELTA" in reason)
        elif not stale and not conflict_reasons and fallback_accumulate:
            action, action_label, action_strength, position_guidance = "ACCUMULATE", "适当买入", 44, "GPMA2 给出研究级修复信号；仅小幅增加多头，等待稳定版或富途对账确认。"
            next_steps = ["若稳定 GPMAPRO 出现最终 B 信号或 GPMA2 完成富途对账，才评估升级为买入。"]
        elif stale or conflict_reasons:
            action_strength, position_guidance = 15, "数据或证据存在否决项；不新增仓位，已有仓位等待确认。"
            next_steps = ["先解决数据新鲜度或方向冲突，再重新评估行动等级。"]
            blocked_by.extend(conflict_reasons)
        elif delta_direction == "BULLISH" or stable_bull:
            next_steps = ["等待另一侧确认：已确认 DELTA LOW 与稳定 GPMAPRO 最终 B 信号需同时成立。"]
            if delta_direction != "BULLISH": blocked_by.append("不在已确认 DELTA LOW 的可交易窗口内。")
            if not stable_bull: blocked_by.append("稳定 GPMAPRO 尚无近期最终 B 信号或底部背离。")
        elif delta_direction == "BEARISH" or stable_bear:
            next_steps = ["等待 DELTA HIGH 与稳定 GPMAPRO 最终 S 信号同时成立，再评估减仓。"]
            if delta_direction != "BEARISH": blocked_by.append("不在已确认 DELTA HIGH 的可交易窗口内。")
            if not stable_bear: blocked_by.append("稳定 GPMAPRO 尚无近期最终 S 信号或顶部背离。")
        if stale and "行情快照不是当前数据，不能形成新的研究候选。" not in blocked_by:
            blocked_by.append("行情快照不是当前数据。")
        if action == "REDUCE" and fallback_reduce:
            summary = "GPMA2 出现研究级卖出信号；存在反向 DELTA 结构时采取适当卖出并继续观察。" if delta_has_low else "GPMA2 出现研究级卖出信号，建议适当卖出并等待稳定版确认。"
        elif action == "ACCUMULATE" and fallback_accumulate:
            summary = "GPMA2 出现研究级买入信号，建议适当买入并等待稳定版确认。"
        base_action, base_action_label, base_action_strength = action, action_label, action_strength
        news: dict[str, Any] = {"status": "UNAVAILABLE", "action": "HOLD", "action_label": "观望", "bias": "NEUTRAL", "score": 0.0,
                                "confidence": 0.0, "validation_status": "INSUFFICIENT_EVIDENCE", "concise_reason": "新闻证据暂不可用，不影响技术结论。",
                                "contribution": {"enabled": False, "points": 0.0, "effect": "NONE"}, "earliest_trade_at": None}
        if _include_news and self.news_advice is not None:
            try:
                news = self.news_advice.advice(symbol, as_of=as_of)
            except Exception as error:
                news = {**news, "concise_reason": f"新闻覆盖层暂不可用：{str(error) or type(error).__name__}"}
        overlay = apply_news_overlay(base_action, base_action_strength, news)
        action, action_strength = overlay["action"], overlay["action_strength"]
        action_label = ACTION_LABEL[action]
        if action != base_action:
            position_guidance = ACTION_GUIDANCE[action]
            blocked_by.append(f"经验证的负面新闻覆盖层将技术行动由{base_action_label}下调为{action_label}，最多下调一级。")
            next_steps = [news["concise_reason"], *next_steps]
        elif overlay["effect"] == "CONFIRM":
            next_steps = [f"新闻因子以 {overlay['applied_points']:+.2f} 点低权重确认当前技术方向。", *next_steps]
        drivers = [
            {"id": "delta", "title": "DELTA 结构", "status": delta_direction, "detail": f"{len(delta['active_windows'])} 个确认后 {DELTA_ACTION_WINDOW_BARS} bar 行动窗口", "date": delta["active_windows"][-1]["actual_date"] if delta["active_windows"] else None},
            {"id": "gpmapro", "title": "稳定 GPMAPRO", "status": gpma1["direction"], "detail": " · ".join(item["code"] for item in [*gpma1["bullish_signals"], *gpma1["bearish_signals"], *gpma1["bullish_divergences"], *gpma1["bearish_divergences"]]) or "近期无最终 B/S 或背离", "date": next((item["date"] for item in evidence if item["source"] == "GPMAPRO"), None)},
            {"id": "gpma2", "title": "GPMA2 研究确认", "status": gpma2["source_status"], "detail": "已对账确认" if gpma2["source_status"] == "AVAILABLE" else "本地等价绘图回退，不单独触发行等级", "date": next((item["date"] for item in evidence if item["source"] == "GPMA2"), None)},
            {"id": "news", "title": "新闻因子", "status": news.get("bias", "NEUTRAL"),
             "detail": f"{news.get('action_label', '观望')}，{news.get('concise_reason', '新闻证据不足')} 总览调整 {overlay['applied_points']:+.2f} 点。",
             "date": None, "detail_target": "NEWS_CENTER"},
        ]
        signal_details = []
        for event in delta["active_windows"]:
            signal_details.append({"source": "DELTA", "signal_code": f"DELTA {event['event_type']}", "date": event["actual_date"], "plain_language": "已确认的时间结构高点。" if event["event_type"] == "HIGH" else "已确认的时间结构低点。", "market_context": f"实际日期 {event['actual_date']}；确认 {event['confirmed_on']}；可交易 {event['tradable_on']}；窗口至 {event.get('delta_window_end', '—')}。", "action_impact": "HIGH 提高减仓警惕；LOW 提高加仓观察。", "confidence": "已确认", "why_now": f"当前仍处于确认后的 {DELTA_ACTION_WINDOW_BARS} bar 行动窗口。", "what_invalidates_it": "行动窗口结束，或出现更近的反向已确认结构。"})
        for indicator in indicators:
            for signal in [*indicator["bullish_signals"], *indicator["bearish_signals"], *indicator["bullish_divergences"], *indicator["bearish_divergences"]]:
                signal_details.append(_guide_detail(indicator["indicator"], signal["code"], signal, symbol=symbol.upper(), trend=indicator["trend"], delta=delta, source_status=indicator["source_status"]))
        rule_trace = {
            "delta_window_bars": DELTA_ACTION_WINDOW_BARS,
            "delta_action_eligible": bool(delta["active_windows"]),
            "stable_gpma_bullish_signal": stable_bull,
            "stable_gpma_bearish_signal": stable_bear,
            "trend_non_bearish": trend_non_bearish,
            "volume_confirmed": volume_confirmed,
            "filters_passed": buy_filters,
            "gpma2_authoritative": gpma2_is_authoritative,
        }
        result = {"symbol": symbol.upper(), "timeframe": timeframe, "as_of": data.date.iloc[-1].date().isoformat(), "snapshot": source, "state": state, "direction": direction, "summary": summary, "research_only": True, "base_action": base_action, "base_action_label": base_action_label, "base_action_strength": base_action_strength, "action": action, "action_label": action_label, "action_strength": action_strength, "position_guidance": position_guidance, "news_overlay": {"status": news.get("status"), "action": news.get("action"), "bias": news.get("bias"), "score": news.get("score"), "confidence": news.get("confidence"), "validation_status": news.get("validation_status"), "reason": news.get("concise_reason"), **overlay}, "rule_id": ACTION_RULE_VERSION, "next_steps": next_steps, "drivers": drivers, "validation": {"status": "PENDING_CALIBRATION", "rule_id": ACTION_RULE_VERSION, "message": "行动等级将按同一规则 ID 接入 DELTA × GPMAPRO 事件研究与样本外验证；当前不以未经校准的历史收益承诺行动结果。"}, "delta": delta, "indicators": indicators, "signal_details": signal_details, "evidence": evidence, "missing_conditions": missing, "conflicts": conflict_reasons, "blocked_by": list(dict.fromkeys(blocked_by)), "action_eligible": action in {"BUY", "ACCUMULATE", "REDUCE", "SELL"}, "rule_trace": {**rule_trace, "news_overlay_applied": overlay["applied_points"]}, "version_agreement": "AGREE" if gpma1["direction"] == gpma2["direction"] else "ONE_NEUTRAL" if "NEUTRAL" in {gpma1["direction"], gpma2["direction"]} else "DISAGREE"}
        if _include_audit:
            authority = (status, script_hash)
            # The audit uses the same research-grade GPMA2 rule as the current
            # action card, while reusing the authority lookup from this request.
            audit_rows = [self.interpret(bars, symbol, timeframe, source, as_of=day.date().isoformat(), _authority=authority, _include_audit=False, _include_news=False, _precomputed_gpma1=gpma1_data, _precomputed_gpma2=gpma2_data) for day in data.date.tail(30)]
            counts: dict[str, int] = {}
            blockers: dict[str, int] = {}
            for row in audit_rows:
                counts[row["action"]] = counts.get(row["action"], 0) + 1
                for reason in row["blocked_by"]:
                    blockers[reason] = blockers.get(reason, 0) + 1
            result["audit"] = {"bars": len(audit_rows), "action_counts": counts, "blocked_by": [{"reason": reason, "count": count} for reason, count in sorted(blockers.items(), key=lambda item: (-item[1], item[0]))], "candidates": [{"date": row["as_of"], "action": row["action"], "label": row["action_label"], "eligible": row["action_eligible"], "blocked_by": row["blocked_by"]} for row in audit_rows if row["action_eligible"] or row["blocked_by"]]}
        return result
