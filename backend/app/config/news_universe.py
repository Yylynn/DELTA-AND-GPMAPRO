"""Fixed, auditable US research universe and company entity aliases."""
from __future__ import annotations

RESEARCH_UNIVERSE: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple", "iphone", "ipad", "mac", "ios", "siri", "vision pro"),
    "MSFT": ("microsoft", "azure", "windows", "linkedin"), "NVDA": ("nvidia", "geforce"),
    "AMZN": ("amazon", "aws", "amazon.com"), "GOOGL": ("alphabet", "google", "youtube"),
    "META": ("meta platforms", "facebook", "instagram", "whatsapp"), "AVGO": ("broadcom",),
    "TSLA": ("tesla",), "AMD": ("advanced micro devices", "amd"), "NFLX": ("netflix",),
    "JPM": ("jpmorgan", "jp morgan"), "V": ("visa",), "MA": ("mastercard",),
    "WMT": ("walmart",), "COST": ("costco",), "XOM": ("exxon", "exxonmobil"),
    "CVX": ("chevron",), "LLY": ("eli lilly", "lilly"), "UNH": ("unitedhealth", "united health"),
    "JNJ": ("johnson & johnson", "johnson and johnson"), "PG": ("procter & gamble", "procter and gamble"),
    "KO": ("coca-cola", "coca cola"), "HD": ("home depot",), "CAT": ("caterpillar",),
    "GE": ("ge aerospace", "general electric"), "IBM": ("ibm", "international business machines"),
    "ORCL": ("oracle",), "QCOM": ("qualcomm",), "CRM": ("salesforce",), "ADBE": ("adobe",),
}

# These aliases improve entity validation for manually queried symbols without
# expanding the fixed research universe used by scheduled factor snapshots.
EXTRA_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "MU": ("micron", "micron technology", "micron technology inc"),
}


def entity_terms(symbol: str) -> tuple[str, ...]:
    value = symbol.upper().removeprefix("US.")
    return (value.casefold(), *RESEARCH_UNIVERSE.get(value, ()), *EXTRA_ENTITY_ALIASES.get(value, ()))


SECTOR_BENCHMARK = {
    **{symbol: "QQQ" for symbol in ("AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "AMD", "NFLX", "IBM", "ORCL", "QCOM", "CRM", "ADBE")},
    **{symbol: "XLF" for symbol in ("JPM", "V", "MA")},
    **{symbol: "XLE" for symbol in ("XOM", "CVX")},
    **{symbol: "XLV" for symbol in ("LLY", "UNH", "JNJ")},
    **{symbol: "XLI" for symbol in ("CAT", "GE")},
}
