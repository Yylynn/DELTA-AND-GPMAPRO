"""Stable research fingerprints plus auditable runtime identity."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _git_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(result.stdout.strip()) if result.returncode == 0 else None


def _workspace_fingerprint(commit: str) -> str:
    """Hash tracked changes and non-ignored untracked files for dirty-run identity."""
    digest = hashlib.sha256(commit.encode("utf-8"))
    try:
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--"], cwd=PROJECT_ROOT,
            capture_output=True, timeout=3, check=False,
        )
        if diff.returncode == 0:
            digest.update(diff.stdout)
        untracked = _git(["ls-files", "--others", "--exclude-standard"])
        for relative in sorted(untracked.splitlines() if untracked else []):
            path = (PROJECT_ROOT / relative).resolve()
            try:
                path.relative_to(PROJECT_ROOT.resolve())
                digest.update(relative.encode("utf-8"))
                digest.update(hashlib.sha256(path.read_bytes()).digest())
            except (OSError, ValueError):
                continue
    except (OSError, subprocess.SubprocessError):
        pass
    return digest.hexdigest()


def code_identity() -> dict[str, Any]:
    """Return deployment-safe source identity without requiring a Git checkout."""
    commit = os.getenv("DELTA_GIT_COMMIT") or _git(["rev-parse", "HEAD"]) or "unknown"
    return {
        "app_version": get_settings().app_version,
        "git_commit": commit,
        "git_dirty": _git_dirty(),
        "workspace_fingerprint": _workspace_fingerprint(commit),
    }


def dataframe_identity(frame: pd.DataFrame) -> dict[str, Any]:
    """Create a deterministic identity for the OHLCV rows actually supplied."""
    columns = [name for name in ("date", "open", "high", "low", "close", "volume") if name in frame.columns]
    canonical = frame.loc[:, columns].copy().sort_values("date").reset_index(drop=True)
    if "date" in canonical:
        canonical["date"] = pd.to_datetime(canonical["date"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    payload = canonical.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode("utf-8")
    dates = canonical["date"] if "date" in canonical and len(canonical) else None
    return {
        "data_sha256": hashlib.sha256(payload).hexdigest(),
        "bar_count": len(canonical),
        "start_date": dates.iloc[0] if dates is not None else None,
        "end_date": dates.iloc[-1] if dates is not None else None,
    }


def local_csv_provenance(frames: dict[str, pd.DataFrame], timeframe: str) -> dict[str, Any]:
    return {
        "source": "local_csv",
        "timeframe": timeframe,
        "datasets": {symbol.upper(): dataframe_identity(frame) for symbol, frame in sorted(frames.items())},
    }


def provenance_sha256(provenance: dict[str, Any], symbol: str | None = None) -> str | None:
    """Resolve one dataset hash or a stable combined hash for multi-dataset exports."""
    if provenance.get("data_sha256"):
        return str(provenance["data_sha256"])
    datasets = provenance.get("datasets") or provenance.get("snapshots") or {}
    if symbol and symbol.upper() in datasets:
        value = datasets[symbol.upper()].get("data_sha256")
        return str(value) if value else None
    hashes = {key: value.get("data_sha256") for key, value in sorted(datasets.items()) if value.get("data_sha256")}
    if not hashes:
        return None
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def research_run_metadata(
    *,
    parameters: dict[str, Any],
    data_provenance: dict[str, Any],
    stable_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build metadata whose fingerprint excludes time and working-tree state."""
    stable = {
        "parameters": parameters,
        "data_provenance": data_provenance,
        "stable_context": stable_context or {},
    }
    fingerprint = hashlib.sha256(
        json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return {
        **stable,
        "fingerprint": fingerprint,
        "generated_at": datetime.now(UTC).isoformat(),
        **code_identity(),
    }
