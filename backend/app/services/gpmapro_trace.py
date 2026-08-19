"""Immutable, user-exported Futu TRACE samples and local reconciliation."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


class TraceSnapshotService:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[3] / "data" / "gpmapro_trace"
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        result = []
        for path in self.root.glob("*.json"):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def import_frame(self, frame: pd.DataFrame, *, reference: str = "futu_desktop_export", metadata: dict | None = None) -> dict:
        if "date" not in frame.columns:
            raise ValueError("TRACE CSV must contain a date column")
        clean = frame.copy()
        clean["date"] = pd.to_datetime(clean["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        clean = clean.dropna(subset=["date"]).drop_duplicates("date", keep="last").sort_values("date")
        if clean.empty:
            raise ValueError("TRACE CSV contains no valid dates")
        content_hash = hashlib.sha256(clean.to_csv(index=False).encode("utf-8")).hexdigest()
        created_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        trace_id = f"GPMAPRO_TRACE_{created_at}_{content_hash[:10]}"
        manifest = {
            "trace_id": trace_id, "reference": reference, "created_at": created_at,
            "content_sha256": content_hash, "rows": len(clean),
            "start_date": clean.date.iloc[0], "end_date": clean.date.iloc[-1],
            "columns": list(clean.columns),
        }
        if metadata:
            manifest.update(metadata)
        clean.to_csv(self.root / f"{trace_id}.csv", index=False)
        (self.root / f"{trace_id}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def load(self, trace_id: str) -> tuple[pd.DataFrame, dict]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", trace_id):
            raise FileNotFoundError(trace_id)
        manifest_path, csv_path = self.root / f"{trace_id}.json", self.root / f"{trace_id}.csv"
        if not manifest_path.exists() or not csv_path.exists():
            raise FileNotFoundError(trace_id)
        frame = pd.read_csv(csv_path)
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        return frame, json.loads(manifest_path.read_text(encoding="utf-8"))

    def compare(self, local: pd.DataFrame, trace: pd.DataFrame, *, tolerance: float = 1e-6) -> dict:
        local_frame = local.copy(); local_frame["date"] = pd.to_datetime(local_frame["date"]).dt.strftime("%Y-%m-%d")
        merged = local_frame.merge(trace, on="date", suffixes=("_local", "_futu"), how="inner")
        columns = sorted(set(local_frame.columns) & set(trace.columns) - {"date"})
        fields: dict[str, dict] = {}
        for column in columns:
            left, right = merged[f"{column}_local"], merged[f"{column}_futu"]
            left_number, right_number = pd.to_numeric(left, errors="coerce"), pd.to_numeric(right, errors="coerce")
            numeric = left_number.notna() & right_number.notna()
            equal = pd.Series(False, index=merged.index)
            equal.loc[numeric] = np.isclose(left_number.loc[numeric], right_number.loc[numeric], rtol=0, atol=tolerance)
            equal.loc[left_number.isna() & right_number.isna()] = True
            equal.loc[~numeric] = left.loc[~numeric].astype(str).str.lower().eq(right.loc[~numeric].astype(str).str.lower())
            mismatches = merged.loc[~equal, ["date", f"{column}_local", f"{column}_futu"]].head(50)
            fields[column] = {"matched": int(equal.sum()), "mismatched": int((~equal).sum()), "examples": mismatches.replace({np.nan: None}).to_dict(orient="records")}
        return {"overlap_rows": len(merged), "fields": fields}
