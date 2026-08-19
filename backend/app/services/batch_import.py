from __future__ import annotations
import re
from pathlib import Path


def import_batch(provider, files: list[tuple[str, bytes]]) -> dict:
    results = []
    for filename, content in files:
        symbol = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).stem.upper())
        try:
            if not filename.lower().endswith(".csv"): raise ValueError("CSV file required")
            _, report = provider.save(symbol, content)
            status = {"UPDATED": "IMPORTED", "UNCHANGED": "UNCHANGED", "REJECTED_OLDER": "REJECTED"}[report["import_status"]]
            results.append({"filename": filename, "symbol": symbol, "status": status, "bars": report["bar_count"], "start_date": report["start_date"], "end_date": report["end_date"], "latest_bar_date": report.get("latest_bar_date", report["end_date"]), "warnings": [report["warning"]] if report.get("warning") else []})
        except ValueError as error:
            results.append({"filename": filename, "symbol": symbol or None, "status": "REJECTED", "warnings": [str(error)]})
    return {"files": len(files), "imported": sum(x["status"] == "IMPORTED" for x in results), "unchanged": sum(x["status"] == "UNCHANGED" for x in results), "rejected": sum(x["status"] == "REJECTED" for x in results), "results": results}
