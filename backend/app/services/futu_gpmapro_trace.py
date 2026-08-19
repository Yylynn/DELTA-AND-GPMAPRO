"""Read-only OpenD calculation of the saved Futu GPMAPRO TRACE indicator."""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass

import pandas as pd

CANONICAL_SHORT_NAME = "GPMAPRO"
CANONICAL_FULL_NAME = "JUSTIN WEAPON"
CANONICAL_SCRIPT_SHA256 = "3a11a5f2252df502f20c95c231b07090d2fcf06a42b2986d83106ce535d2b664"

@dataclass
class FutuTraceResult:
    frame: pd.DataFrame
    script_sha256: str | None
    outputs: list[str]


class FutuGpmaProTraceClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self.host, self.port = host, port

    def calculate(self, bars: pd.DataFrame, *, symbol: str, short_name: str = CANONICAL_SHORT_NAME) -> FutuTraceResult:
        """Calculate a saved MyLang indicator against supplied OHLCV bars only."""
        from futu import (  # Imported lazily so the app can run without OpenD.
            IndicatorCalcHandlerBase, IndicatorLangType, IndicatorSearchMode,
            KLType, OpenQuoteContext, RET_OK,
        )

        context = OpenQuoteContext(host=self.host, port=self.port)
        done, payload = threading.Event(), {}

        class Handler(IndicatorCalcHandlerBase):
            def on_recv_rsp(self, rsp_pb):  # type: ignore[no-untyped-def]
                ret, data = super().on_recv_rsp(rsp_pb)
                payload["ret"], payload["data"] = ret, data
                done.set()
                return ret, data

        try:
            context.set_handler(Handler())
            ret, entries = context.get_indicator_list(short_name, IndicatorLangType.MYLANG, IndicatorSearchMode.EXACT)
            if ret != RET_OK or not entries:
                raise RuntimeError(f"OpenD could not read {short_name}: {entries}")
            indicator = entries[0]["my_lang"]
            script = indicator["script"]
            # Current OpenD releases expose the saved script for some calls but
            # may omit it from get_indicator_list while still returning the
            # complete output contract.  Do not mislabel the hash of an empty
            # string as an indicator fingerprint.
            script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest() if script else None
            if short_name == CANONICAL_SHORT_NAME and (
                indicator["full_name"] != CANONICAL_FULL_NAME or (script_hash is not None and script_hash != CANONICAL_SCRIPT_SHA256)
            ):
                raise RuntimeError("Futu GPMAPRO source differs from the locked JUSTIN WEAPON authority")
            input_bars = bars.rename(columns={"date": "time_key"}).copy()
            ret, calc_id = context.request_indicator_calc_async(short_name, IndicatorLangType.MYLANG, symbol, KLType.K_DAY, input_bars)
            if ret != RET_OK:
                raise RuntimeError(f"OpenD indicator calculation request failed: {calc_id}")
            if not done.wait(timeout=20):
                raise RuntimeError("OpenD indicator calculation timed out")
            if payload["ret"] != RET_OK:
                raise RuntimeError(f"OpenD indicator calculation failed: {payload['data']}")
            result = payload["data"]
            names = [item["name"] for item in result["outputs"]]
            records = [{"date": row["time"], **dict(zip(names, row["values"], strict=True))} for row in result["output_rows"]]
            return FutuTraceResult(pd.DataFrame(records), script_hash, names)
        finally:
            context.close()
