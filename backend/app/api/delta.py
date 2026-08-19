import csv
import io
import json
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from app.quant.delta_time import DeltaEventType, ManualDeltaEngine

router = APIRouter(tags=["DELTA"])
store = Path(__file__).resolve().parents[3] / "data" / "delta_events.json"


class DeltaEventIn(BaseModel):
    symbol: str = "*"
    event_type: DeltaEventType
    cycle_type: str = "MANUAL"
    anchor_date: str
    published_at: str | None = None
    expected_date: str
    tolerance_days: int = Field(ge=0)
    confidence: float = Field(default=1, ge=0, le=1)
    enabled: bool = True
    source: str = "MANUAL"
    notes: str | None = None
    metadata: dict = {}


def load():
    return json.loads(store.read_text(encoding="utf-8")) if store.exists() else []


def save(events):
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def normalized(item: dict) -> dict:
    item = {**item}
    item["symbol"] = str(item.get("symbol") or "*").upper()
    item["source"] = str(item.get("source") or "MANUAL").upper()
    item["published_at"] = str(item.get("published_at") or item["anchor_date"])
    item.setdefault("created_at", datetime.utcnow().isoformat(timespec="seconds") + "Z")
    return item


def duplicate(events: list[dict], item: dict) -> bool:
    return any(all(str(existing.get(key, "*")).upper() == str(item.get(key, "*")).upper() for key in ("symbol", "event_type", "anchor_date", "expected_date")) for existing in events)


def conflict(events: list[dict], item: dict) -> bool:
    return any(existing.get("symbol", "*").upper() == item["symbol"] and existing.get("expected_date") == item["expected_date"] and existing.get("event_type") != item["event_type"] for existing in events)


@router.get("/delta/events")
def events(): return {"events": load()}


@router.get("/delta/windows")
def windows(): return {"windows": [w.model_dump(mode="json") for w in ManualDeltaEngine([x for x in load() if x.get("enabled", True)]).windows()]}


@router.post("/delta/events")
def create(item: DeltaEventIn):
    values = normalized(item.model_dump()); events = load()
    if duplicate(events, values): raise HTTPException(409, "DUPLICATE")
    values["event_id"] = str(uuid.uuid4()); values["conflicting_events"] = conflict(events, values)
    save(events + [values]); return values


@router.put("/delta/events/{event_id}")
def update(event_id: str, item: DeltaEventIn):
    events = load()
    for index, event in enumerate(events):
        if event["event_id"] == event_id:
            values = normalized(item.model_dump()); values["event_id"] = event_id; values["created_at"] = event.get("created_at", values["created_at"])
            events[index] = values; save(events); return values
    raise HTTPException(404, "DELTA event not found")


@router.delete("/delta/events/{event_id}")
def delete(event_id: str):
    events = load(); remaining = [x for x in events if x["event_id"] != event_id]
    if len(remaining) == len(events): raise HTTPException(404, "DELTA event not found")
    save(remaining); return {"success": True}


@router.get("/delta/import-template")
def template():
    return {"csv": "symbol,event_type,anchor_date,published_at,expected_date,tolerance_days,confidence,enabled\nAAPL,LOW,2023-10-20,2023-10-20,2023-10-27,3,0.80,true\n"}


@router.post("/delta/import")
async def bulk_import(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".csv"): raise HTTPException(422, "CSV file required")
    try: rows = list(csv.DictReader(io.StringIO((await file.read()).decode("utf-8-sig"))))
    except UnicodeDecodeError: raise HTTPException(422, "CSV must be UTF-8")
    events = load(); batch_id = str(uuid.uuid4()); results = []
    for row in rows:
        try:
            enabled = str(row.get("enabled", "true")).lower() in {"true", "1", "yes"}
            item = DeltaEventIn(symbol=row.get("symbol", ""), event_type=row.get("event_type", ""), anchor_date=row.get("anchor_date", ""), published_at=row.get("published_at") or None, expected_date=row.get("expected_date", ""), tolerance_days=int(row.get("tolerance_days", 0)), confidence=float(row.get("confidence", 1)), enabled=enabled, source="IMPORTED", notes=row.get("notes") or None)
            values = normalized(item.model_dump())
            # Parse ISO dates now, before persisting.
            datetime.fromisoformat(values["anchor_date"]); datetime.fromisoformat(values["published_at"]); datetime.fromisoformat(values["expected_date"])
            if duplicate(events, values): results.append({"symbol": values["symbol"], "status": "DUPLICATE"}); continue
            values.update({"event_id": str(uuid.uuid4()), "import_batch": batch_id, "conflicting_events": conflict(events, values)})
            events.append(values); results.append({"symbol": values["symbol"], "status": "CONFLICTING_EVENTS" if values["conflicting_events"] else "IMPORTED", "event_id": values["event_id"]})
        except (ValueError, TypeError) as error: results.append({"symbol": row.get("symbol"), "status": "REJECTED", "error": str(error)})
    save(events)
    return {"import_batch": batch_id, "imported": sum(x["status"] == "IMPORTED" for x in results), "duplicates": sum(x["status"] == "DUPLICATE" for x in results), "conflicts": sum(x["status"] == "CONFLICTING_EVENTS" for x in results), "rejected": sum(x["status"] == "REJECTED" for x in results), "results": results}
