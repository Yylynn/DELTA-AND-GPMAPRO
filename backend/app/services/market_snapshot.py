"""Provider-neutral immutable market-data snapshots.

Yahoo Finance is the zero-configuration default.  Futu OpenD remains an
optional provider and legacy Futu snapshots remain readable in place.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from app.data.providers import validate_ohlcv
from app.services.futu_snapshot import FutuSnapshotService


class MarketDataError(RuntimeError):
    pass


class HistorySnapshotProvider(Protocol):
    def fetch_history_snapshot(
        self, code: str, timeframe: str = "1d", adjustment: str = "adjusted",
        start: str = "2018-01-01", end: str | None = None,
    ) -> dict: ...


def _resample(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == "1d":
        return frame
    if timeframe not in {"1w", "1mo"}:
        raise ValueError("timeframe must be 1d, 1w or 1mo")
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.set_index("date")
    rule = "W-FRI" if timeframe == "1w" else "ME"
    result = data.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna().reset_index()
    last_dates = data["close"].resample(rule).apply(lambda values: values.index[-1]).reset_index(drop=True)
    result["date"] = pd.to_datetime(last_dates).dt.strftime("%Y-%m-%d")
    return result


def _snapshot_payload(frame: pd.DataFrame) -> bytes:
    """Stable text representation so float parsing cannot invalidate a snapshot."""
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.10f").encode("utf-8")


class YahooSnapshotService:
    source = "yahoo_finance"

    def __init__(self, root: Path | None = None, ticker_factory=None):
        self.root = root or Path(__file__).resolve().parents[3] / "data" / "market_snapshots"
        self.root.mkdir(parents=True, exist_ok=True)
        self._ticker_factory = ticker_factory

    @staticmethod
    def normalise_code(code: str) -> tuple[str, str]:
        value = code.strip().upper()
        if "." not in value:
            value = f"US.{value}"
        match = re.fullmatch(r"(US|HK|SH|SZ)\.([A-Z0-9._-]+)", value)
        if not match:
            raise ValueError("code must be US.AAPL, HK.00700, SH.600519 or SZ.000001")
        market, symbol = match.groups()
        if market == "US":
            yahoo = symbol
        elif market == "HK":
            if not symbol.isdigit():
                raise ValueError("Hong Kong symbols must be numeric")
            yahoo = f"{symbol.zfill(4)}.HK"
        elif market == "SH":
            yahoo = f"{symbol}.SS"
        else:
            yahoo = f"{symbol}.SZ"
        return value, yahoo

    def _ticker(self, symbol: str):
        if self._ticker_factory:
            return self._ticker_factory(symbol)
        try:
            import yfinance as yf
        except ImportError as error:  # pragma: no cover - deployment guard
            raise MarketDataError("yfinance is not installed") from error
        return yf.Ticker(symbol)

    def list(self) -> list[dict]:
        manifests = []
        for path in self.root.glob("*.json"):
            try:
                manifests.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return sorted(manifests, key=lambda item: item.get("fetched_at", ""), reverse=True)

    def load(self, snapshot_id: str) -> tuple[pd.DataFrame, dict]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", snapshot_id):
            raise FileNotFoundError(snapshot_id)
        manifest_path, csv_path = self.root / f"{snapshot_id}.json", self.root / f"{snapshot_id}.csv"
        if not manifest_path.exists() or not csv_path.exists():
            raise FileNotFoundError(snapshot_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frame, quality = validate_ohlcv(pd.read_csv(csv_path))
        payload = _snapshot_payload(frame)
        actual = hashlib.sha256(payload).hexdigest()
        if manifest.get("data_sha256") and manifest["data_sha256"] != actual:
            raise ValueError("SNAPSHOT_INTEGRITY_ERROR: CSV content does not match manifest SHA-256")
        return frame, {**quality, **manifest, "data_sha256": actual, "source": "yahoo_snapshot"}

    def status(self) -> dict:
        items = self.list()
        latest = items[0] if items else None
        try:
            library_version = version("yfinance")
        except PackageNotFoundError:
            library_version = "not_installed"
        return {
            "provider": "yahoo", "status": "AVAILABLE" if library_version != "not_installed" else "UNAVAILABLE",
            "requires_api_key": False, "library_version": library_version,
            "last_success_at": latest.get("fetched_at") if latest else None,
            "last_snapshot_id": latest.get("snapshot_id") if latest else None,
            "snapshot_count": len(items),
            "usage": "personal_research_only",
        }

    def fetch_history_snapshot(
        self, code: str, timeframe: str = "1d", adjustment: str = "adjusted",
        start: str = "2018-01-01", end: str | None = None,
    ) -> dict:
        code, yahoo_symbol = self.normalise_code(code)
        timeframe, adjustment = timeframe.lower(), adjustment.lower()
        if timeframe not in {"1d", "1w", "1mo"}:
            raise ValueError("timeframe must be 1d, 1w or 1mo")
        if adjustment not in {"adjusted", "raw"}:
            raise ValueError("adjustment must be adjusted or raw")
        requested_end = end or datetime.now(UTC).date().isoformat()
        try:
            exclusive_end = (date.fromisoformat(requested_end) + timedelta(days=1)).isoformat()
            ticker = self._ticker(yahoo_symbol)
            raw = ticker.history(
                start=start, end=exclusive_end, interval="1d", actions=False,
                auto_adjust=adjustment == "adjusted", repair=True, timeout=15, raise_errors=True,
            )
        except Exception as error:
            raise MarketDataError(f"Yahoo Finance history request failed for {yahoo_symbol}: {error}") from error
        if raw is None or raw.empty:
            raise MarketDataError(f"Yahoo Finance returned no history for {yahoo_symbol}")
        data = raw.reset_index()
        date_column = next((column for column in data.columns if str(column).lower() in {"date", "datetime"}), data.columns[0])
        data = data.rename(columns={
            date_column: "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
        })
        daily, daily_quality = validate_ohlcv(data)
        clean = _resample(daily, timeframe)
        clean, quality = validate_ohlcv(clean)
        fetched_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        safe_code = re.sub(r"[^A-Z0-9]+", "_", code).strip("_")
        snapshot_id = f"YAHOO_{safe_code}_{timeframe.upper()}_{adjustment.upper()}_{fetched_at}"
        payload = _snapshot_payload(clean)
        try:
            library_version = version("yfinance")
        except PackageNotFoundError:
            library_version = "unknown"
        manifest = {
            "schema_version": 2, "snapshot_id": snapshot_id, "source": self.source,
            "provider": "yahoo", "provider_symbol": yahoo_symbol, "code": code,
            "timeframe": timeframe, "adjustment": adjustment,
            "autype": "QFQ" if adjustment == "adjusted" else "NONE",
            "requested_start": start, "requested_end": requested_end, "fetched_at": fetched_at,
            "data_sha256": hashlib.sha256(payload).hexdigest(), "library_version": library_version,
            "daily_source_bar_count": daily_quality["bar_count"],
            "usage": "personal_research_only", **quality,
        }
        (self.root / f"{snapshot_id}.csv").write_bytes(payload)
        (self.root / f"{snapshot_id}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest


class MarketSnapshotService:
    """Facade selecting the configured writer while reading every legacy source."""

    def __init__(
        self, provider_name: str = "yahoo", yahoo: YahooSnapshotService | None = None,
        futu: FutuSnapshotService | None = None,
    ):
        value = provider_name.strip().lower()
        if value not in {"yahoo", "futu"}:
            raise ValueError("market_data_provider must be yahoo or futu")
        self.provider_name = value
        self.yahoo = yahoo or YahooSnapshotService()
        self.futu = futu or FutuSnapshotService()

    def list(self) -> list[dict]:
        return sorted([*self.yahoo.list(), *self.futu.list()], key=lambda item: item.get("fetched_at", ""), reverse=True)

    def load(self, snapshot_id: str) -> tuple[pd.DataFrame, dict]:
        try:
            return self.yahoo.load(snapshot_id)
        except FileNotFoundError:
            return self.futu.load(snapshot_id)

    def status(self) -> dict:
        active = self.yahoo.status() if self.provider_name == "yahoo" else self.futu.connection_status()
        return {"active_provider": self.provider_name, "active": active, "snapshot_count": len(self.list())}

    def fetch_history_snapshot(
        self, code: str, timeframe: str = "1d", adjustment: str = "adjusted",
        start: str = "2018-01-01", end: str | None = None,
    ) -> dict:
        if self.provider_name == "yahoo":
            return self.yahoo.fetch_history_snapshot(code, timeframe, adjustment, start, end)
        autype = {"adjusted": "QFQ", "raw": "NONE"}.get(adjustment.lower())
        if autype is None:
            raise ValueError("adjustment must be adjusted or raw")
        return self.futu.fetch_history_snapshot(code, timeframe, autype, start, end)
