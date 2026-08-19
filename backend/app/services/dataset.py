from __future__ import annotations
import hashlib
import json
from datetime import date
from pathlib import Path
from app.config.dataset_config import DATASET_CONFIG
from app.services.data_freshness import freshness_snapshot

RESEARCH_BASKET = {
    "SPY": "美国宽基", "QQQ": "成长/科技", "IWM": "小盘", "XLF": "金融", "XLE": "能源", "XLV": "医疗", "XLI": "工业", "XLU": "公用事业",
}


def eligibility(bars: int) -> str:
    if bars >= DATASET_CONFIG.eligible_min_bars: return "ELIGIBLE"
    if bars >= DATASET_CONFIG.limited_min_bars: return "LIMITED"
    return "INELIGIBLE"


def symbol_metadata(provider, symbol: str) -> dict:
    frame, quality = provider.ohlcv(symbol)
    freshness = freshness_snapshot(str(frame.date.iloc[-1]), len(frame))
    return {"symbol": symbol.upper(), "bars": len(frame), "start_date": str(frame.date.iloc[0]), "end_date": str(frame.date.iloc[-1]), "latest_bar_date": str(frame.date.iloc[-1]), "freshness": freshness["freshness"], "research_eligibility": eligibility(len(frame))}


def universe(provider) -> list[dict]: return [symbol_metadata(provider, symbol) for symbol in provider.symbols()]


def coverage(provider) -> dict:
    rows = universe(provider); eligible = {row["symbol"] for row in rows if row["research_eligibility"] == "ELIGIBLE"}
    basket = [{"symbol": symbol, "category": category, "eligible": symbol in eligible, "present": any(row["symbol"] == symbol for row in rows)} for symbol, category in RESEARCH_BASKET.items()]
    spans = [row["start_date"] for row in rows if row["symbol"] in eligible], [row["end_date"] for row in rows if row["symbol"] in eligible]
    return {"eligible_symbols": len(eligible), "required_symbols": DATASET_CONFIG.readiness_eligible_symbols, "basket": basket, "basket_coverage": sum(item["eligible"] for item in basket), "common_date_range": {"start": max(spans[0]) if spans[0] else None, "end": min(spans[1]) if spans[1] else None}, "status": "READY" if len(eligible) >= DATASET_CONFIG.readiness_eligible_symbols and sum(item["eligible"] for item in basket) >= 6 else "NOT_READY"}


def sha256_file(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(provider, delta_events: list[dict]) -> dict:
    rows = []
    for symbol in provider.symbols():
        item = symbol_metadata(provider, symbol); path = provider.root / f"{symbol}.csv"
        item.update({"filename": path.name, "sha256": sha256_file(path), "delta_event_count": sum(e.get("symbol", "*").upper() in {"*", symbol.upper()} for e in delta_events)})
        rows.append(item)
    normalized = sorted(delta_events, key=lambda e: (str(e.get("symbol", "*")), str(e.get("event_type")), str(e.get("anchor_date")), str(e.get("expected_date")), str(e.get("event_id", ""))))
    return {"created_at": date.today().isoformat(), "symbols": rows, "delta_event_fingerprint": hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}
