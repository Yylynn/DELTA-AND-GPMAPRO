"""Read-only Futu OpenD historical-bar snapshots.

Snapshots are immutable research evidence: every fetch keeps its own CSV and
manifest, so a later OpenD update can never silently alter a reconciliation.
"""
from __future__ import annotations

import json
import re
import hashlib
import socket
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.data.providers import validate_ohlcv


class FutuOpenDError(RuntimeError):
    pass


class FutuSnapshotService:
    def __init__(self, root: Path | None = None, host: str = "127.0.0.1", port: int = 11111):
        self.root = root or Path(__file__).resolve().parents[3] / "data" / "futu_snapshots"
        self.root.mkdir(parents=True, exist_ok=True)
        self.host, self.port = host, port

    def list(self) -> list[dict]:
        manifests = []
        for path in self.root.glob("*.json"):
            try:
                manifests.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return sorted(manifests, key=lambda item: item["fetched_at"], reverse=True)

    def _ensure_endpoint(self) -> None:
        """Fail fast before the SDK's long connection retry loop."""
        try:
            with socket.create_connection((self.host, self.port), timeout=1):
                return
        except OSError as error:
            raise FutuOpenDError(f"OpenD is unavailable at {self.host}:{self.port}; start OpenD and confirm API port 11111: {error}") from error

    def load(self, snapshot_id: str) -> tuple[pd.DataFrame, dict]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", snapshot_id):
            raise FileNotFoundError(snapshot_id)
        manifest_path = self.root / f"{snapshot_id}.json"
        csv_path = self.root / f"{snapshot_id}.csv"
        if not manifest_path.exists() or not csv_path.exists():
            raise FileNotFoundError(snapshot_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frame, quality = validate_ohlcv(pd.read_csv(csv_path))
        # Legacy snapshots predate explicit hashes.  Derive the hash in memory
        # without rewriting their immutable manifest, so they remain auditable.
        data_sha256 = manifest.get("data_sha256") or hashlib.sha256(
            frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        ).hexdigest()
        return frame, {**quality, **manifest, "data_sha256": data_sha256, "source": "futu_opend_snapshot"}

    def quota(self) -> dict:
        self._ensure_endpoint()
        try:
            from futu import OpenQuoteContext, RET_OK
        except ImportError as error:  # pragma: no cover - deployment guard
            raise FutuOpenDError("Futu Python SDK is not installed") from error
        context = OpenQuoteContext(host=self.host, port=self.port)
        try:
            ret, result = context.get_history_kl_quota(get_detail=False)
            if ret != RET_OK:
                raise FutuOpenDError(f"OpenD quota check failed: {result}")
            used, remaining, *_ = result
            return {"used": int(used), "remaining": int(remaining), "host": self.host, "port": self.port}
        except Exception as error:
            if isinstance(error, FutuOpenDError):
                raise
            raise FutuOpenDError(f"OpenD is unavailable at {self.host}:{self.port}: {error}") from error
        finally:
            context.close()

    @staticmethod
    def _normalise_code(code: str) -> str:
        value = code.strip().upper()
        if not re.fullmatch(r"(?:US|HK|SH|SZ|JP|SG|AU|CA|UK)\.[A-Z0-9._-]+", value):
            raise ValueError("code must be a Futu market code such as US.AAPL or HK.00700")
        return value

    @staticmethod
    def _enum_values(timeframe: str, autype: str):
        try:
            from futu import AuType, KLType
        except ImportError as error:  # pragma: no cover
            raise FutuOpenDError("Futu Python SDK is not installed") from error
        ktypes = {"1d": KLType.K_DAY, "1w": KLType.K_WEEK, "1mo": KLType.K_MON}
        autypes = {"QFQ": AuType.QFQ, "HFQ": AuType.HFQ, "NONE": AuType.NONE}
        if timeframe not in ktypes:
            raise ValueError("timeframe must be 1d, 1w or 1mo")
        if autype not in autypes:
            raise ValueError("autype must be QFQ, HFQ or NONE")
        return ktypes[timeframe], autypes[autype]

    def fetch_history_snapshot(self, code: str, timeframe: str = "1d", autype: str = "QFQ", start: str = "2018-01-01", end: str | None = None) -> dict:
        """Fetch a read-only, immutable historical-bar evidence snapshot."""
        code, timeframe, autype = self._normalise_code(code), timeframe.lower(), autype.upper()
        ktype, au_type = self._enum_values(timeframe, autype)
        end = end or datetime.now(UTC).date().isoformat()
        quota = self.quota()
        if quota["remaining"] <= 0:
            raise FutuOpenDError("OpenD historical K-line quota is exhausted")
        try:
            import futu
            from futu import OpenQuoteContext, RET_OK
        except ImportError as error:  # pragma: no cover
            raise FutuOpenDError("Futu Python SDK is not installed") from error
        context = OpenQuoteContext(host=self.host, port=self.port)
        pages: list[pd.DataFrame] = []
        key = None
        try:
            while True:
                ret, page, key = context.request_history_kline(
                    code, start=start, end=end, ktype=ktype, autype=au_type,
                    max_count=1000, page_req_key=key,
                )
                if ret != RET_OK:
                    raise FutuOpenDError(f"OpenD historical K-line request failed: {page}")
                pages.append(page)
                if key is None:
                    break
        except Exception as error:
            if isinstance(error, FutuOpenDError):
                raise
            raise FutuOpenDError(f"OpenD historical K-line request failed: {error}") from error
        finally:
            context.close()
        raw = pd.concat(pages, ignore_index=True)
        clean, quality = validate_ohlcv(raw[["time_key", "open", "high", "low", "close", "volume"]].rename(columns={"time_key": "date"}))
        fetched_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        safe_code = re.sub(r"[^A-Z0-9]+", "_", code).strip("_")
        snapshot_id = f"{safe_code}_{timeframe.upper()}_{autype}_{fetched_at}"
        payload = clean.to_csv(index=False, lineterminator="\n").encode("utf-8")
        manifest = {
            "snapshot_id": snapshot_id, "source": "futu_opend", "code": code,
            "timeframe": timeframe, "autype": autype, "requested_start": start,
            "requested_end": end, "fetched_at": fetched_at, "quota": quota,
            "data_sha256": hashlib.sha256(payload).hexdigest(),
            "sdk_version": getattr(futu, "__version__", "unknown"),
            "opend_endpoint": f"{self.host}:{self.port}",
            "opend_version": "not_reported_by_sdk",
            **quality,
        }
        clean.to_csv(self.root / f"{snapshot_id}.csv", index=False)
        (self.root / f"{snapshot_id}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def fetch_daily_qfq(self, code: str = "US.AAPL", start: str = "2018-01-01", end: str | None = None) -> dict:
        """Compatibility entry point for the original AAPL reconciliation flow."""
        return self.fetch_history_snapshot(code=code, timeframe="1d", autype="QFQ", start=start, end=end)
