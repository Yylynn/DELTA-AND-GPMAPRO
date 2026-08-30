"""Versioned, liquid US equity and ETF universe for the stock-pool workspace."""
from __future__ import annotations

# This is deliberately a maintained list rather than a daily top-performers
# query.  Its membership can be reconstructed for each saved scan.
STOCK_POOL_UNIVERSE_VERSION = "US_LIQUID_CORE_2026Q3"

STOCK_POOL_UNIVERSE: dict[str, str] = {
    # Broad market, factor and sector ETFs
    "SPY": "宽基 ETF", "QQQ": "宽基 ETF", "DIA": "宽基 ETF", "IWM": "宽基 ETF",
    "XLK": "科技 ETF", "SMH": "半导体 ETF", "SOXX": "半导体 ETF", "XLF": "金融 ETF",
    "XLV": "医疗 ETF", "XLE": "能源 ETF", "XLI": "工业 ETF", "XLY": "可选消费 ETF",
    "XLP": "必选消费 ETF", "XLU": "公用事业 ETF", "XLB": "材料 ETF", "XLRE": "房地产 ETF",
    "TLT": "利率 ETF", "HYG": "信用 ETF", "GLD": "黄金 ETF", "USO": "原油 ETF",
    # Technology and communications
    "AAPL": "科技", "MSFT": "科技", "NVDA": "半导体", "AVGO": "半导体",
    "AMD": "半导体", "QCOM": "半导体", "MU": "半导体", "INTC": "半导体",
    "AMZN": "可选消费", "GOOGL": "通信服务", "META": "通信服务", "NFLX": "通信服务",
    "ORCL": "软件", "CRM": "软件", "ADBE": "软件", "NOW": "软件", "PLTR": "软件",
    "PANW": "网络安全", "CRWD": "网络安全", "CSCO": "网络设备", "IBM": "科技",
    "TSLA": "可选消费", "UBER": "可选消费", "BKNG": "可选消费", "MCD": "可选消费",
    # Financials
    "JPM": "金融", "BAC": "金融", "WFC": "金融", "GS": "金融", "MS": "金融",
    "V": "支付", "MA": "支付", "AXP": "支付", "BLK": "资产管理", "SCHW": "金融",
    # Healthcare
    "LLY": "医疗", "UNH": "医疗", "JNJ": "医疗", "ABBV": "医疗", "MRK": "医疗",
    "TMO": "医疗设备", "ABT": "医疗设备", "ISRG": "医疗设备", "AMGN": "生物科技", "GILD": "生物科技",
    # Industrials, energy and materials
    "GE": "工业", "CAT": "工业", "DE": "工业", "HON": "工业", "RTX": "工业",
    "LMT": "工业", "BA": "工业", "UNP": "运输", "UPS": "运输", "FDX": "运输",
    "XOM": "能源", "CVX": "能源", "COP": "能源", "SLB": "能源", "EOG": "能源",
    "LIN": "材料", "FCX": "材料", "NEM": "材料",
    # Consumer staples and real estate
    "WMT": "必选消费", "COST": "必选消费", "PG": "必选消费", "KO": "必选消费",
    "PEP": "必选消费", "HD": "可选消费", "LOW": "可选消费", "NKE": "可选消费",
    "AMT": "房地产", "PLD": "房地产", "EQIX": "房地产",
}
