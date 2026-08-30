"""Traceable US-market event radar built from permitted news metadata."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.config.news_sources import SOURCES

OFFICIAL_SOURCES = frozenset({"fed_press", "treasury_press"})
HORIZONS = (1, 3, 5)
CLUSTER_WINDOW = timedelta(hours=24)
SECTOR_BENCHMARK = {
    "金融": "XLF", "支付": "XLF", "科技": "XLK", "软件": "XLK", "硬件": "XLK",
    "半导体": "SOXX", "可选消费": "XLY", "零售": "XRT", "鞋服": "XRT", "服装": "XRT", "工业": "XLI", "能源": "XLE",
    "医疗": "XLV", "制药": "XLV", "医保": "XLV", "加密资产": "IBIT",
    "加密服务": "IBIT", "加密矿业": "IBIT",
}
ETF_ASSETS = frozenset({"XLF", "XLK", "XLY", "XLI", "XLE", "XLV", "SOXX", "IBIT", "XRT"})
SOURCE_PRIORITY = {source.source_id: source.priority for source in SOURCES if source.scope == "MARKET"}
INDUSTRY_ORDER = ("科技", "金融", "消费", "医疗", "能源", "工业", "加密", "宏观综合")
SECTOR_INDUSTRY = {
    "科技": "科技", "软件": "科技", "硬件": "科技", "半导体": "科技",
    "金融": "金融", "支付": "金融",
    "可选消费": "消费", "零售": "消费", "鞋服": "消费", "服装": "消费",
    "医疗": "医疗", "制药": "医疗", "医保": "医疗",
    "能源": "能源", "工业": "工业",
    "加密资产": "加密", "加密服务": "加密", "加密矿业": "加密",
}

# Explicit, auditable transmission map. SPY/QQQ only serve as benchmarks.
THEMES: dict[str, dict[str, Any]] = {
    "POLICY_REGULATION": {"label": "政策与监管", "terms": ("bill", "law", "act", "regulation", "sec", "监管", "法案", "立法", "批准"), "direction": 0,
        "targets": (("XLF", "金融", 0, "政策与监管可能改变金融机构的合规与资本成本。"), ("JPM", "金融", 0, "大型银行对金融监管和流动性条件较敏感。"), ("V", "支付", 0, "支付网络可能受监管规则变化影响。"), ("MA", "支付", 0, "支付网络可能受监管规则变化影响。"))},
    "LIQUIDITY_TREASURY": {"label": "财政与流动性", "terms": ("treasury", "buyback", "liquidity", "auction", "财政部", "回购", "流动性", "国债"), "direction": 1,
        "targets": (("XLF", "金融", 1, "流动性改善通常先影响金融条件。"), ("JPM", "金融", 1, "流动性与国债市场变化会影响大型银行的资金环境。"), ("V", "支付", 1, "风险偏好和消费支付活动可能受流动性支持。"), ("MA", "支付", 1, "风险偏好和消费支付活动可能受流动性支持。"))},
    "RATES_INFLATION": {"label": "利率与通胀", "terms": ("fed", "interest rate", "inflation", "cpi", "yield", "降息", "加息", "通胀", "收益率", "美联储"), "direction": -1,
        "targets": (("XLF", "金融", 0, "利率变化对金融板块的净息差与信用风险方向并不固定。"), ("JPM", "金融", 0, "银行对利率路径敏感，需结合收益率曲线验证。"), ("XLK", "科技", -1, "更高贴现率通常压制高久期科技资产估值。"), ("NVDA", "半导体", -1, "半导体估值对贴现率和风险偏好较敏感。"), ("MSFT", "软件", -1, "大型软件股估值对贴现率和风险偏好较敏感。"))},
    "GROWTH": {"label": "增长与需求", "terms": ("recession", "jobs", "gdp", "consumer", "demand", "衰退", "就业", "经济", "消费", "需求"), "direction": 0,
        "targets": (("XLY", "可选消费", 0, "消费与就业变化通过可选消费需求传导。"), ("AMZN", "可选消费", 0, "消费需求变化可能影响电商与云服务预期。"), ("TSLA", "可选消费", 0, "可选消费与融资环境会影响汽车需求预期。"), ("HD", "可选消费", 0, "住房与消费者支出变化会影响家居改善需求。"), ("XLI", "工业", 0, "增长与资本开支变化会影响工业订单。"), ("CAT", "工业", 0, "基建和资本开支变化会影响工程设备需求。"), ("GE", "工业", 0, "经济活动和航空/工业投资会影响订单预期。"))},
    "RETAIL_CONSUMER": {"label": "零售与鞋服消费", "terms": ("retail", "retailer", "footwear", "apparel", "sporting goods", "零售", "鞋类", "服装", "体育用品"), "direction": -1,
        "targets": (("XRT", "零售", -1, "零售商的业绩或需求警讯可能传导至零售板块预期。"), ("XLY", "可选消费", -1, "可选消费景气变化可能影响零售和品牌需求。"), ("DKS", "零售", -1, "该事件直接涉及 Dick's Sporting Goods 的经营与盈利预期。"), ("NKE", "鞋服", -1, "鞋类市场走弱可能影响相关品牌的需求预期。"), ("ANF", "服装", -1, "零售与服装消费景气可能影响同业估值。"))},
    "TRADE": {"label": "贸易与出口管制", "terms": ("tariff", "trade war", "export control", "关税", "贸易", "出口管制"), "direction": -1,
        "targets": (("XLK", "科技", -1, "关税或出口限制可能扰动科技供应链和海外收入。"), ("AAPL", "硬件", -1, "全球供应链与海外销售使硬件公司对贸易限制敏感。"), ("NVDA", "半导体", -1, "出口管制可能直接影响高端芯片可服务市场。"), ("AVGO", "半导体", -1, "全球供应链与海外销售使半导体公司对贸易限制敏感。"), ("AMD", "半导体", -1, "出口管制可能限制部分芯片市场。"), ("QCOM", "半导体", -1, "全球手机供应链对贸易限制敏感。"), ("XLI", "工业", -1, "关税与贸易摩擦可能提高工业供应链成本。"), ("CAT", "工业", -1, "海外工程需求和供应链受贸易条件影响。"), ("GE", "工业", -1, "航空与工业供应链受贸易条件影响。"))},
    "GEOPOLITICS_ENERGY": {"label": "地缘与能源", "terms": ("war", "sanction", "oil", "opec", "地缘", "制裁", "原油", "能源"), "direction": -1,
        "targets": (("XLE", "能源", 1, "若事件推升原油供给风险，能源价格可能获得支撑。"), ("XOM", "能源", 1, "上游能源企业对油价上行更直接敏感。"), ("CVX", "能源", 1, "上游能源企业对油价上行更直接敏感。"), ("XLI", "工业", -1, "地缘冲突和高能源成本可能增加工业成本与不确定性。"), ("CAT", "工业", -1, "全球项目与投入成本可能受地缘风险扰动。"))},
    "TECH_RISK_APPETITE": {"label": "科技风险偏好", "terms": ("ai", "semiconductor", "chip", "risk appetite", "人工智能", "芯片", "半导体", "风险偏好"), "direction": 1,
        "targets": (("SOXX", "半导体", 1, "AI 与芯片需求预期首先传导至半导体行业。"), ("XLK", "科技", 1, "科技风险偏好改善通常支持行业估值。"), ("NVDA", "半导体", 1, "AI 算力需求变化可能影响 GPU 预期。"), ("AMD", "半导体", 1, "AI 与数据中心竞争格局可能影响芯片预期。"), ("AVGO", "半导体", 1, "定制芯片与网络需求可能受 AI 投资周期带动。"), ("QCOM", "半导体", 1, "终端 AI 和芯片需求变化可能影响预期。"), ("MSFT", "软件", 1, "AI 云服务变现预期可能影响软件估值。"), ("ORCL", "软件", 1, "云与 AI 基础设施需求可能影响订单预期。"))},
    "HEALTHCARE_REGULATION": {"label": "医疗监管", "terms": ("drug pricing", "fda", "medicare", "healthcare", "药价", "医保", "药品", "医疗监管"), "direction": 0,
        "targets": (("XLV", "医疗", 0, "医疗政策可能改变定价、报销或审批预期。"), ("LLY", "制药", 0, "药价、审批和报销变化可能影响制药盈利预期。"), ("UNH", "医保", 0, "医保规则与报销变化可能影响保险与服务利润。"), ("JNJ", "医疗", 0, "监管与审批变化可能影响医疗产品组合。"))},
    "CRYPTO_POLICY": {"label": "加密政策与流动性", "terms": ("bitcoin", "crypto", "stablecoin", "digital asset", "比特币", "加密", "稳定币", "数字资产"), "direction": 1,
        "targets": (("IBIT", "加密资产", 1, "加密政策和流动性变化可直接影响现货比特币风险偏好。"), ("COIN", "加密服务", 1, "交易活跃度和监管清晰度可能影响交易平台预期。"), ("MSTR", "加密资产", 1, "公司资产负债表对比特币价格高度敏感。"), ("MARA", "加密矿业", 1, "矿企盈利对比特币价格和风险偏好敏感。"), ("RIOT", "加密矿业", 1, "矿企盈利对比特币价格和风险偏好敏感。"), ("CLSK", "加密矿业", 1, "矿企盈利对比特币价格和风险偏好敏感。"))},
}


def _text(item: dict[str, Any]) -> str:
    return re.sub(r"<[^>]+>", " ", f"{item.get('title') or ''} {item.get('summary') or ''}").casefold()


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", value.casefold()) + re.findall(r"[\u3400-\u9fff]{2,}", value))


def _matches_term(text: str, term: str) -> bool:
    """Match English terms as whole phrases: ``ai`` must not match ``retail``."""
    if re.fullmatch(r"[a-z0-9 ]+", term.casefold()):
        return re.search(rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])", text.casefold()) is not None
    return term.casefold() in text.casefold()


def _published_at(item: dict[str, Any]) -> pd.Timestamp | None:
    try:
        stamp = pd.Timestamp(item.get("published_at"))
        return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    except (TypeError, ValueError):
        return None


class MarketEventRadarService:
    """Produces traceable research observations, never trading orders or causal claims."""

    def __init__(self, news, alerts, root: Path, translator=None) -> None:
        self.news, self.alerts, self.root, self.translator = news, alerts, root, translator

    @staticmethod
    def _classify(item: dict[str, Any]) -> list[str]:
        text = _text(item)
        return [key for key, spec in THEMES.items() if any(_matches_term(text, term) for term in spec["terms"])]

    @staticmethod
    def _same_event(item: dict[str, Any], group: list[dict[str, Any]]) -> bool:
        anchor = group[0]
        if not (set(anchor["radar_themes"]) & set(item["radar_themes"])) or len(_terms(_text(anchor)) & _terms(_text(item))) < 2:
            return False
        first, second = _published_at(anchor), _published_at(item)
        return first is not None and second is not None and abs(first - second) <= CLUSTER_WINDOW

    @staticmethod
    def _confirmation(sources: list[str]) -> tuple[str, str, float]:
        official = [source for source in sources if source in OFFICIAL_SOURCES]
        if official: return "CONFIRMED", f"已确认：{official[0]} 为官方发布。", .95
        if len(sources) >= 2: return "CONFIRMED", f"已确认：{len(sources)} 个独立来源交叉佐证。", .78
        source = sources[0] if sources else "未知来源"
        return "PENDING", f"待确认：目前仅 {source} 1 个非官方来源；不需要人工操作，等待独立来源佐证。", .43

    @staticmethod
    def _transmission(themes: list[str]) -> list[dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for theme in themes:
            label = THEMES[theme]["label"]
            for asset, sector, direction, mechanism in THEMES[theme]["targets"]:
                row = {"asset": asset, "sector": sector, "direction": "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "UNCERTAIN", "basis": f"{label}：{mechanism}", "theme": theme, "kind": "ETF" if asset in ETF_ASSETS else "STOCK"}
                current = output.get(asset)
                if current is None or (current["direction"] == "UNCERTAIN" and row["direction"] != "UNCERTAIN"):
                    output[asset] = row
                elif current["direction"] != row["direction"] and row["direction"] != "UNCERTAIN":
                    current["direction"] = "UNCERTAIN"; current["basis"] = f"{current['basis']}；同时存在方向相反的主题，暂不下结论。"
        # Keep a card actionable: show the most direct, predefined chains
        # rather than turning a multi-theme headline into a broad market list.
        return list(output.values())[:12]

    @staticmethod
    def _industries(transmission: list[dict[str, Any]]) -> list[str]:
        """Map explicit transmission sectors to stable, user-facing industry filters."""
        matched = {SECTOR_INDUSTRY[row["sector"]] for row in transmission if row.get("sector") in SECTOR_INDUSTRY}
        return [industry for industry in INDUSTRY_ORDER if industry in matched] or ["宏观综合"]

    @staticmethod
    def _interpretation(title: str | None, summary: str | None, themes: list[str], transmission: list[dict[str, Any]]) -> dict[str, str]:
        labels = "、".join(THEMES[theme]["label"] for theme in themes)
        headline = str(title or "").strip()
        lower = headline.casefold()
        if summary:
            fact_summary = re.sub(r"<[^>]+>", " ", str(summary)).strip()
        elif "misses expectations" in lower and "footwear" in lower:
            company = re.split(r"\s+stock\s+falls?\b", headline, flags=re.I)[0].strip() or "该公司"
            fall = re.search(r"stock\s+falls?\s+(\d+%)", headline, flags=re.I)
            fact_summary = f"{company} 业绩未达市场预期，并称鞋类市场环境具有挑战" + (f"；报道提到其股价下跌 {fall.group(1)}" if fall else "。")
        elif headline:
            fact_summary = f"头条事实：{headline}"
        else:
            fact_summary = "来源未提供足够的标题或摘要，无法可靠总结事件内容。"
        directions = {row["direction"] for row in transmission}
        direct = [row["asset"] for row in transmission if row["kind"] == "STOCK"][:3]
        sectors = list(dict.fromkeys(row["sector"] for row in transmission))[:3]
        if directions == {"BULLISH"}:
            conclusion = f"直接层：重点关注 {'、'.join(direct) or '相关公司'} 的预期变化。后续层：{'、'.join(sectors) or '相关行业'} 可能受益，但仍须由价格和更多来源验证。"
        elif directions == {"BEARISH"}:
            conclusion = f"直接层：重点关注 {'、'.join(direct) or '相关公司'} 的盈利或需求预期压力。后续层：{'、'.join(sectors) or '相关行业'} 可能承压，但不能据此推定所有同业都会下跌。"
        else:
            conclusion = f"直接层：{'、'.join(direct) or '尚无可靠的直接受影响公司'}。后续层：事件可能涉及 {'、'.join(sectors) or labels}，但方向并不一致或证据不足，因此不对整体方向下结论。"
        return {"fact_summary": fact_summary, "basis": f"事实层：新闻网站 RSS 头条命中“{labels}”主题。", "conclusion": conclusion,
                "limitation": "解读仅使用发布方标题与 RSS 摘要；系统不抓取正文，也不把推断表述为因果。"}

    def _clusters(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: list[list[dict[str, Any]]] = []
        for raw in items:
            themes = self._classify(raw)
            if not themes: continue
            item = {**raw, "radar_themes": themes}
            target = next((group for group in groups if self._same_event(item, group)), None)
            if target is None: groups.append([item])
            else: target.append(item)
        events = []
        for group in groups:
            representative = max(group, key=lambda row: (row.get("source_id") in OFFICIAL_SOURCES, bool(row.get("summary"))))
            themes = sorted({theme for row in group for theme in row["radar_themes"]})
            sources = sorted({str(row.get("source_id") or row.get("source") or "未知来源") for row in group})
            confirmation, reason, source_confidence = self._confirmation(sources)
            summaries = sum(bool(row.get("summary")) for row in group)
            completeness = round(min(.95, .35 + .25 * summaries + .10 * sum(bool(row.get("url")) for row in group)), 2)
            score = sum(THEMES[theme]["direction"] for theme in themes) / max(1, len(themes))
            evidence = [{key: row.get(key) for key in ("id", "title", "summary", "source", "source_id", "publisher", "published_at", "url")} for row in group]
            transmission = self._transmission(themes)
            source_id = str(representative.get("source_id") or "")
            headline_kind = "官方发布" if source_id in OFFICIAL_SOURCES else "网站头条"
            headline_priority = SOURCE_PRIORITY.get(source_id, 99)
            events.append({"event_id": f"macro:{representative.get('id')}", "title": representative.get("title"), "summary": representative.get("summary"), "published_at": representative.get("published_at"), "themes": [{"id": theme, "label": THEMES[theme]["label"]} for theme in themes], "industries": self._industries(transmission), "direction_score": round(score, 3), "confidence": round((source_confidence + completeness) / 2, 3), "confirmation": confirmation, "confirmation_reason": reason, "source_confidence": source_confidence, "information_completeness": completeness, "headline": {"kind": headline_kind, "priority": headline_priority, "reason": f"{representative.get('publisher') or representative.get('source') or source_id} 发布的 RSS 头条。"}, "interpretation": self._interpretation(representative.get("title"), representative.get("summary"), themes, transmission), "transmission": transmission, "evidence": evidence, "representative_source": {key: representative.get(key) for key in ("source", "source_id", "publisher", "url", "published_at")}})
        return sorted(events, key=lambda row: (row["headline"]["priority"], -row["source_confidence"], -(_published_at(row).timestamp() if _published_at(row) is not None else 0)))

    @staticmethod
    def _scenarios(score: float, risk: bool) -> list[dict[str, str]]:
        posture = "偏防御" if risk or score <= -.15 else "偏进攻" if score >= .15 else "中性"
        return [{"kind": "基准", "text": f"当前研究级市场姿态为{posture}；在证据未增加前，以风险暴露管理而非追逐单条新闻为主。"}, {"kind": "转强", "text": "若支持风险偏好的事件获得第二来源确认，且相关行业技术信号未转弱，可提高关注。"}, {"kind": "转弱", "text": "若风险事件扩散、波动率预警升级或行业出现下行技术信号，应优先降低高波动风险暴露。"}]

    def _market_frames(self, symbols: set[str]) -> dict[str, pd.DataFrame]:
        fetch = getattr(self.alerts, "_fetch_yahoo_daily_bars", None)
        if not callable(fetch): return {}
        frames: dict[str, pd.DataFrame] = {}
        def load(symbol: str) -> tuple[str, pd.DataFrame]:
            frame = fetch(symbol).copy(); frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
            return symbol, frame.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(symbols))), thread_name_prefix="event-radar") as pool:
            futures = [pool.submit(load, symbol) for symbol in sorted(symbols)]
            for future in as_completed(futures):
                try:
                    symbol, frame = future.result()
                    frames[symbol] = frame
                except Exception:
                    continue
        return frames

    @staticmethod
    def _start_position(frame: pd.DataFrame, published_at: str | None) -> int | None:
        try:
            stamp = pd.Timestamp(published_at)
            if stamp.tzinfo is None: stamp = stamp.tz_localize("UTC")
            day = stamp.tz_convert("America/New_York").tz_localize(None).normalize()
        except (TypeError, ValueError): return None
        positions = np.flatnonzero(frame["date"] > day)  # Avoid same-session daily-data leakage.
        return int(positions[0]) if len(positions) else None

    @classmethod
    def _return_series(cls, frame: pd.DataFrame | None, published_at: str | None) -> dict[str, float]:
        if frame is None: return {}
        start = cls._start_position(frame, published_at)
        if start is None: return {}
        return {f"{horizon}d": round(float(frame.close.iloc[start + horizon] / frame.close.iloc[start] - 1), 4) for horizon in HORIZONS if start + horizon < len(frame)}

    @classmethod
    def _reaction(cls, event: dict[str, Any], frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not event.get("published_at"): return {"status": "UNAVAILABLE", "items": [], "message": "新闻未提供发布时间，无法确定事件后的观察窗口。"}
        if not frames: return {"status": "UNAVAILABLE", "items": [], "message": "相关标的行情不可用，暂无法计算事件后反应。"}
        items = []
        for target in event["transmission"]:
            asset = target["asset"]
            benchmark = "SPY" if target["kind"] == "ETF" else SECTOR_BENCHMARK.get(target["sector"], "SPY")
            returns, benchmark_returns = cls._return_series(frames.get(asset), event["published_at"]), cls._return_series(frames.get(benchmark), event["published_at"])
            excess = {horizon: round(value - benchmark_returns[horizon], 4) for horizon, value in returns.items() if horizon in benchmark_returns}
            if returns: items.append({**target, "benchmark": benchmark, "returns": returns, "excess_returns": excess})
        if items: return {"status": "AVAILABLE", "items": items, "message": "使用事件后的首个完整交易日为起点；收益与超额收益仅记录观察结果，不证明因果。"}
        future = any(cls._start_position(frame, event["published_at"]) is not None for frame in frames.values())
        return {"status": "PENDING" if future else "UNAVAILABLE", "items": [], "message": "等待足够的后续完整交易日以形成 1、3、5 日反应。" if future else "相关标的没有事件后的可用日线。"}

    @classmethod
    def _returns(cls, frames: dict[str, pd.DataFrame], published_at: str | None) -> dict[str, Any]:
        output = {symbol: cls._return_series(frame, published_at) for symbol, frame in frames.items()}
        output = {symbol: values for symbol, values in output.items() if values}
        return {"status": "AVAILABLE" if output else "PENDING", "returns": output}

    def _validation(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        folder = self.root / "market_event_snapshots"; snapshots = []
        for path in sorted(folder.glob("*.json")) if folder.exists() else []:
            try: snapshots.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError): continue
        sessions, benchmarks = len(snapshots), {symbol: frame for symbol, frame in frames.items() if symbol in {"SPY", "QQQ"}}
        if sessions < 60 or not benchmarks: return {"status": "INSUFFICIENT_EVIDENCE", "session_count": sessions, "horizons": list(HORIZONS), "reason": f"需要至少 60 个交易日的不可变事件快照和后续市场基准行情；当前为 {sessions} 个交易日。"}
        horizons = []
        for horizon in HORIZONS:
            scores, targets = [], []
            for snapshot in snapshots:
                values = [row.get(f"{horizon}d") for row in self._returns(benchmarks, snapshot.get("captured_at")).get("returns", {}).values() if row.get(f"{horizon}d") is not None]
                if values: scores.append(float(snapshot.get("market_score", 0))); targets.append(float(np.mean(values)))
            corr = float(stats.spearmanr(scores, targets).statistic) if len(scores) >= 3 else 0.0
            horizons.append({"horizon": horizon, "sample_count": len(scores), "spearman_ic": round(corr if np.isfinite(corr) else 0.0, 4), "status": "PASSED" if len(scores) >= 30 and corr >= .02 else "INSUFFICIENT_EVIDENCE"})
        validated = sessions >= 60 and all(item["status"] == "PASSED" for item in horizons)
        return {"status": "VALIDATED" if validated else "INSUFFICIENT_EVIDENCE", "session_count": sessions, "horizons": horizons, "reason": None if validated else "宏观事件分数尚未通过全部 1、3、5 日样本外检验。"}

    def insight(self, *, refresh: bool = False) -> dict[str, Any]:
        response = self.news.get_market(limit=100, refresh=refresh); events = self._clusters(list(response.get("market_items", [])))
        visible_events = events[:30]
        if self.translator is not None:
            translations = self.translator.translate_many([str(event.get("title") or "") for event in visible_events])
            for event in visible_events:
                event["translated_title"] = translations.get(str(event.get("title") or ""))
        alerts = self.alerts.snapshot(); active = alerts.get("active_alerts", [])
        frames = self._market_frames({"SPY", "QQQ"} | {row["asset"] for event in events for row in event["transmission"]})
        for event in events: event["reaction"] = self._reaction(event, frames)
        risk = any(item.get("severity") == "RISK" for item in active)
        score = sum(float(event["direction_score"]) * float(event["confidence"]) for event in events) / max(1, len(events)); posture = "DEFENSIVE" if risk or score <= -.15 else "CONSTRUCTIVE" if score >= .15 else "NEUTRAL"
        payload = {"schema_version": 2, "captured_at": datetime.now(timezone.utc).isoformat(), "market_score": round(score, 4), "posture": posture, "events": events, "active_alerts": active, "source_fetched_at": response.get("fetched_at")}
        folder = self.root / "market_event_snapshots"; folder.mkdir(parents=True, exist_ok=True); path = folder / f"{payload['captured_at'][:10]}.json"
        if not path.exists(): path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        industry_counts = {industry: sum(industry in event["industries"] for event in visible_events) for industry in INDUSTRY_ORDER}
        headline_event_map = {str(item.get("id")): event["event_id"] for event in visible_events for item in event.get("evidence", []) if item.get("id")}
        return {"posture": posture, "market_score": round(score, 4), "confidence": round(min(.85, .20 + .08 * len(events) + (.12 if active else 0)), 3), "events": visible_events, "industry_counts": {key: value for key, value in industry_counts.items() if value}, "headline_event_map": headline_event_map, "scenarios": self._scenarios(score, risk), "validation": self._validation(frames), "active_alerts": active, "market_items": response.get("market_items", []), "fetched_at": response.get("fetched_at"), "source_status": response.get("source_status"), "warning": response.get("warning"), "source_health": response.get("source_health", [])}
