"""Unified, read-only dataset catalogue for the new backtest laboratory."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.services.data_freshness import freshness_snapshot
from app.services.dataset import eligibility, sha256_file


LOCAL_PREFIX = "local_csv:"
FUTU_PREFIX = "futu_snapshot:"
MARKET_PREFIX = "market_snapshot:"
BACKTEST_HISTORY_START = "2018-01-01"


class BacktestDatasetCatalog:
    """Expose local CSV files and immutable Futu snapshots through one contract."""

    def __init__(self, provider, futu_snapshots, market_snapshots=None):
        self.provider = provider
        self.futu_snapshots = futu_snapshots
        self.market_snapshots = market_snapshots

    @staticmethod
    def _freshness(end_date: str | None, bars: int) -> dict:
        return freshness_snapshot(end_date, bars)

    def _local_dataset(self, symbol: str, *, verify: bool = False, loaded=None) -> dict:
        frame, quality = loaded or self.provider.ohlcv(symbol)
        bars = len(frame)
        start_date = str(frame.date.iloc[0])
        end_date = str(frame.date.iloc[-1])
        path = self.provider.root / f"{symbol.upper()}.csv"
        row = {
            "dataset_id": f"{LOCAL_PREFIX}{symbol.upper()}",
            "source": "local_csv",
            "symbol": symbol.upper(),
            "timeframe": "1d",
            "bar_count": bars,
            "start_date": start_date,
            "end_date": end_date,
            "autype": None,
            "adjustment": "UNRECORDED",
            "research_eligibility": eligibility(bars),
            "quality": quality.get("quality", "UNKNOWN"),
            "warnings": list(quality.get("warnings", [])),
            "snapshot_id": None,
            "data_sha256": sha256_file(path),
            "fetched_at": None,
            "selectable": True,
            **self._freshness(end_date, bars),
        }
        if verify:
            row["verification"] = "VERIFIED"
        return row

    def _futu_dataset(self, manifest: dict, *, verify: bool = False) -> dict:
        snapshot_id = str(manifest.get("snapshot_id", ""))
        if not snapshot_id:
            raise ValueError("Futu snapshot manifest is missing snapshot_id")
        metadata = manifest
        if verify:
            _, metadata = self.futu_snapshots.load(snapshot_id)
        timeframe = str(metadata.get("timeframe", "")).lower()
        bars = int(metadata.get("bar_count", 0))
        start_date = metadata.get("start_date")
        end_date = metadata.get("end_date")
        warnings = list(metadata.get("warnings", []))
        if timeframe != "1d":
            warnings.append("新回测实验室第一版只支持日线数据。")
        row = {
            "dataset_id": f"{FUTU_PREFIX}{snapshot_id}",
            "source": "futu_snapshot",
            "symbol": str(metadata.get("code", "")).upper(),
            "timeframe": timeframe,
            "bar_count": bars,
            "start_date": start_date,
            "end_date": end_date,
            "autype": metadata.get("autype"),
            "adjustment": metadata.get("autype") or "UNRECORDED",
            "research_eligibility": eligibility(bars),
            "quality": metadata.get("quality", "UNKNOWN"),
            "warnings": warnings,
            "snapshot_id": snapshot_id,
            "data_sha256": metadata.get("data_sha256"),
            "fetched_at": metadata.get("fetched_at"),
            "selectable": timeframe == "1d" and bars > 0,
            **self._freshness(str(end_date) if end_date else None, bars),
        }
        if verify:
            row["verification"] = "VERIFIED"
        return row

    def _market_dataset(self, manifest: dict, *, verify: bool = False) -> dict:
        if self.market_snapshots is None:
            raise ValueError("market snapshot service is unavailable")
        snapshot_id = str(manifest.get("snapshot_id", ""))
        if not snapshot_id:
            raise ValueError("Yahoo snapshot manifest is missing snapshot_id")
        metadata = manifest
        if verify:
            _, metadata = self.market_snapshots.load(snapshot_id)
        if str(metadata.get("provider", "")).lower() != "yahoo":
            raise ValueError("backtest symbol loading only accepts Yahoo snapshots")
        timeframe = str(metadata.get("timeframe", "")).lower()
        bars = int(metadata.get("bar_count", 0))
        end_date = metadata.get("end_date")
        warnings = list(metadata.get("warnings", []))
        if timeframe != "1d":
            warnings.append("回测实验室第一版只支持日线数据。")
        row = {
            "dataset_id": f"{MARKET_PREFIX}{snapshot_id}",
            "source": "yahoo",
            "symbol": str(metadata.get("code", "")).upper(),
            "timeframe": timeframe,
            "bar_count": bars,
            "start_date": metadata.get("start_date"),
            "end_date": end_date,
            "autype": metadata.get("autype"),
            "adjustment": metadata.get("adjustment") or "adjusted",
            "research_eligibility": eligibility(bars),
            "quality": metadata.get("quality", "UNKNOWN"),
            "warnings": warnings,
            "snapshot_id": snapshot_id,
            "data_sha256": metadata.get("data_sha256"),
            "fetched_at": metadata.get("fetched_at"),
            "selectable": timeframe == "1d" and bars > 0,
            **self._freshness(str(end_date) if end_date else None, bars),
        }
        if verify:
            row["verification"] = "VERIFIED"
        return row

    @staticmethod
    def _local_snapshot_date(fetched_at: str | None):
        if not fetched_at:
            return None
        value = str(fetched_at)
        try:
            if value.endswith("Z") and "T" in value and "-" not in value[:8]:
                parsed = datetime.strptime(value, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
            else:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone().date()
        except ValueError:
            return None

    def load_symbol(self, code: str, *, refresh: bool = False) -> dict:
        """Fetch or reuse today's Yahoo daily snapshot and load it for backtesting."""
        if self.market_snapshots is None:
            raise ValueError("market snapshot service is unavailable")
        yahoo = self.market_snapshots.yahoo
        normalised_code, _ = yahoo.normalise_code(code)
        today = datetime.now().astimezone().date()
        cached = next((
            item for item in yahoo.list()
            if str(item.get("provider", "")).lower() == "yahoo"
            and str(item.get("code", "")).upper() == normalised_code
            and str(item.get("timeframe", "")).lower() == "1d"
            and str(item.get("adjustment", "")).lower() == "adjusted"
            and item.get("requested_start") == BACKTEST_HISTORY_START
            and self._local_snapshot_date(item.get("fetched_at")) == today
        ), None)
        if cached is not None and not refresh:
            manifest = cached
            cache_status = "HIT"
        else:
            manifest = yahoo.fetch_history_snapshot(
                normalised_code,
                timeframe="1d",
                adjustment="adjusted",
                start=BACKTEST_HISTORY_START,
            )
            cache_status = "REFRESHED" if refresh else "FETCHED"
        result = self.load([f"{MARKET_PREFIX}{manifest['snapshot_id']}"])
        result.update({
            "provider": "yahoo",
            "cache_status": cache_status,
            "snapshot_fetched_at": manifest.get("fetched_at"),
        })
        return result

    def list(self) -> list[dict]:
        local = [self._local_dataset(symbol) for symbol in self.provider.symbols()]
        futu = [self._futu_dataset(manifest) for manifest in self.futu_snapshots.list()]
        return local + futu

    def _resolve(self, dataset_id: str) -> dict:
        _, metadata = self.read(dataset_id)
        return metadata

    def read(self, dataset_id: str):
        """Return one revalidated daily frame and its unified metadata."""
        if dataset_id.startswith(LOCAL_PREFIX):
            symbol = dataset_id.removeprefix(LOCAL_PREFIX).strip().upper()
            if not symbol:
                raise ValueError("local CSV dataset id is missing a symbol")
            loaded = self.provider.ohlcv(symbol)
            return loaded[0], self._local_dataset(symbol, verify=True, loaded=loaded)
        if dataset_id.startswith(FUTU_PREFIX):
            snapshot_id = dataset_id.removeprefix(FUTU_PREFIX).strip()
            if not snapshot_id:
                raise ValueError("Futu dataset id is missing a snapshot id")
            frame, metadata = self.futu_snapshots.load(snapshot_id)
            row = self._futu_dataset(metadata)
            row["verification"] = "VERIFIED"
            return frame, row
        if dataset_id.startswith(MARKET_PREFIX):
            if self.market_snapshots is None:
                raise ValueError("market snapshot service is unavailable")
            snapshot_id = dataset_id.removeprefix(MARKET_PREFIX).strip()
            if not snapshot_id:
                raise ValueError("market snapshot dataset id is missing a snapshot id")
            frame, metadata = self.market_snapshots.load(snapshot_id)
            row = self._market_dataset(metadata)
            row["verification"] = "VERIFIED"
            return frame, row
        raise ValueError(f"unknown backtest dataset id: {dataset_id}")

    def load(self, dataset_ids: list[str]) -> dict:
        unique_ids = list(dict.fromkeys(dataset_ids))
        if not unique_ids:
            raise ValueError("select at least one dataset")
        if len(unique_ids) > 20:
            raise ValueError("the first backtest laboratory version accepts at most 20 datasets")
        datasets = [self._resolve(dataset_id) for dataset_id in unique_ids]
        if any(not dataset["selectable"] for dataset in datasets):
            raise ValueError("all selected datasets must contain daily bars")
        sources = {dataset["source"] for dataset in datasets}
        if len(sources) != 1:
            raise ValueError("select local CSV or Futu snapshots in one load, not both")

        starts = [dataset["start_date"] for dataset in datasets if dataset["start_date"]]
        ends = [dataset["end_date"] for dataset in datasets if dataset["end_date"]]
        common_start = max(starts) if starts else None
        common_end = min(ends) if ends else None
        warnings = [
            f"{dataset['symbol']}：{warning}"
            for dataset in datasets
            for warning in dataset["warnings"]
        ]
        if common_start and common_end and common_start > common_end:
            warnings.append("所选数据集没有共同日期区间；后续只能逐标的研究。")
        levels = {dataset["research_eligibility"] for dataset in datasets}
        selection_eligibility = (
            "INELIGIBLE" if "INELIGIBLE" in levels
            else "LIMITED" if "LIMITED" in levels
            else "ELIGIBLE"
        )
        fingerprint_payload = [
            {"dataset_id": dataset["dataset_id"], "data_sha256": dataset["data_sha256"]}
            for dataset in datasets
        ]
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "selection_id": fingerprint,
            "loaded_at": datetime.now(UTC).isoformat(),
            "source": next(iter(sources)),
            "dataset_count": len(datasets),
            "datasets": datasets,
            "common_date_range": {"start": common_start, "end": common_end},
            "research_eligibility": selection_eligibility,
            "warnings": warnings,
        }
