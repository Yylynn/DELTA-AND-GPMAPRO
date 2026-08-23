"""Persistent, single-worker research runs for long causal strategy replays."""
from __future__ import annotations

import csv
import hashlib
import json
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from app.services.research_metadata import code_identity


class ForecastCache:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def get(self, key: str) -> list[dict] | None:
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload["forecasts"] if payload.get("key") == key else None
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def put(self, key: str, forecasts: list[dict]) -> None:
        path = self._path(key)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"key": key, "forecasts": forecasts}, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)


class StrategyLabRunStore:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[3] / "data" / "strategy_lab_runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache = ForecastCache(self.root / "forecast_cache")
        self._lock = threading.Lock()
        self._active: str | None = None
        self._recover_interrupted_runs()

    def _recover_interrupted_runs(self) -> None:
        """A worker thread cannot survive a backend reload; never leave it seemingly live."""
        for path in self.root.glob("*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if state.get("status") in {"QUEUED", "RUNNING"}:
                state.update({"status": "FAILED", "completed_at": datetime.now(UTC).isoformat(), "error": "RUN_INTERRUPTED_BY_BACKEND_RESTART"})
                temp = path.with_suffix(".tmp")
                temp.write_text(json.dumps(state, ensure_ascii=False, default=str), encoding="utf-8")
                temp.replace(path)

    def _path(self, run_id: str) -> Path:
        if not run_id or not run_id.isalnum():
            raise FileNotFoundError(run_id)
        return self.root / f"{run_id}.json"

    def _read(self, run_id: str) -> dict:
        return json.loads(self._path(run_id).read_text(encoding="utf-8"))

    def _write(self, run_id: str, payload: dict) -> None:
        path = self._path(run_id)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        temp.replace(path)

    @staticmethod
    def fingerprint(request: dict, snapshots: dict[str, dict], research_context: dict | None = None) -> str:
        identity = code_identity()
        stable = {"request": request, "snapshots": snapshots, "research_context": research_context or {}, "code": {"git_commit": identity["git_commit"], "workspace_fingerprint": identity["workspace_fingerprint"]}}
        return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def create_or_reuse(self, request: dict, snapshots: dict[str, dict], runner: Callable, research_context: dict | None = None) -> dict:
        fingerprint = self.fingerprint(request, snapshots, research_context)
        with self._lock:
            for path in self.root.glob("*.json"):
                try:
                    saved = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if saved.get("fingerprint") == fingerprint and saved.get("status") in {"QUEUED", "RUNNING", "COMPLETED"}:
                    return self.status(saved["run_id"], reused=True)
            if self._active:
                raise RuntimeError("A full-history strategy research run is already active")
            run_id = hashlib.sha256(f"{fingerprint}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()[:16]
            payload = {"run_id": run_id, "fingerprint": fingerprint, "status": "QUEUED", "created_at": datetime.now(UTC).isoformat(), "request": request, "snapshots": snapshots, "research_context": research_context or {}, "progress": {"stage": "queued", "progress": 0.0, "completed_symbols": 0, "total_symbols": len(snapshots), "symbol": None}, "result": None, "error": None}
            self._write(run_id, payload)
            self._active = run_id
            thread = threading.Thread(target=self._execute, args=(run_id, runner), daemon=True, name=f"strategy-lab-{run_id}")
            thread.start()
            return self.status(run_id, reused=False)

    def _execute(self, run_id: str, runner: Callable) -> None:
        def update(progress: dict) -> None:
            with self._lock:
                state = self._read(run_id)
                state["progress"] = progress
                state["status"] = "RUNNING"
                self._write(run_id, state)
        try:
            update({"stage": "preparing", "progress": 0.0, "completed_symbols": 0, "total_symbols": self._read(run_id)["progress"]["total_symbols"], "symbol": None})
            result = runner(update)
            with self._lock:
                state = self._read(run_id)
                state.update({"status": "COMPLETED", "completed_at": datetime.now(UTC).isoformat(), "progress": {"stage": "complete", "progress": 1.0, "completed_symbols": state["progress"]["total_symbols"], "total_symbols": state["progress"]["total_symbols"], "symbol": None}, "result": result})
                self._write(run_id, state)
        except Exception as error:  # pragma: no cover - exact worker failures depend on data/vendor runtime
            with self._lock:
                state = self._read(run_id)
                state.update({"status": "FAILED", "completed_at": datetime.now(UTC).isoformat(), "error": str(error), "traceback": traceback.format_exc()})
                self._write(run_id, state)
        finally:
            with self._lock:
                if self._active == run_id:
                    self._active = None

    def status(self, run_id: str, *, reused: bool = False) -> dict:
        state = self._read(run_id)
        return {key: state.get(key) for key in ("run_id", "fingerprint", "status", "created_at", "completed_at", "progress", "error")} | {"reused": reused}

    def result(self, run_id: str) -> dict:
        state = self._read(run_id)
        if state.get("status") != "COMPLETED":
            raise RuntimeError(state.get("error") or "RUN_NOT_COMPLETED")
        return state["result"]

    def export_csv(self, run_id: str) -> str:
        result = self.result(run_id)
        metadata = result.get("run_metadata", {})
        provenance = metadata.get("data_provenance", {})
        rows = [["entry_rule", "exit_rule", "sample_count", "average_net_return", "random_average_net_return", "b_only_average_net_return", "edge_vs_random", "assessment", "failed_checks", "run_fingerprint", "git_commit", "generated_at", "data_provenance"]]
        for item in result["strategies"]:
            rows.append([item["entry_rule"], item["exit_rule"], item["metrics"]["sample_count"], item["metrics"]["average_net_return"], item["random_baseline"]["average_net_return"], item["b_only_baseline"]["average_net_return"], item["net_edge_vs_random"], item["research_assessment"]["label"], ";".join(item["research_assessment"]["failed_checks"]), metadata.get("fingerprint"), metadata.get("git_commit"), metadata.get("generated_at"), json.dumps(provenance, ensure_ascii=False, sort_keys=True)])
        from io import StringIO
        output = StringIO(); writer = csv.writer(output); writer.writerows(rows)
        return output.getvalue()
