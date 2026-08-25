"""Signal-enriched OHLCV preview for the new backtest laboratory."""
from __future__ import annotations

import pandas as pd

from app.quant.delta_time import ITDDeltaEngine
from app.services.gpmaapro_engine import GpmaAproEngine, SIGNALS


BUY_SIGNALS = tuple(code for code in SIGNALS if code.startswith("b"))
SELL_SIGNALS = tuple(code for code in SIGNALS if code.startswith("s"))
DELTA_SIGNALS = ("DELTA_LOW", "DELTA_HIGH")
DIVERGENCE_SIGNALS = (
    ("BOTTOM_FACE", "bottom_1_y", "BUY"),
    ("TOP_FACE", "top_1_y", "SELL"),
    ("BOTTOM_ARROW_2", "bottom_2_y", "BUY"),
    ("TOP_ARROW_2", "top_2_y", "SELL"),
)


class BacktestSignalPreviewService:
    def __init__(self, catalog, gpma=None, delta=None):
        self.catalog = catalog
        self.gpma = gpma or GpmaAproEngine()
        self.delta = delta or ITDDeltaEngine()

    @staticmethod
    def _bar(row) -> dict:
        return {
            "date": row.date.date().isoformat(),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }

    @staticmethod
    def describe_signals(full_counts: dict[str, int], display_counts: dict[str, int] | None = None) -> list[dict]:
        shown = full_counts if display_counts is None else display_counts
        return [
            {
                "code": signal.upper(),
                "family": "B" if signal in BUY_SIGNALS else "S",
                "direction": "BUY" if signal in BUY_SIGNALS else "SELL",
                "full_count": full_counts[signal.upper()],
                "display_count": shown[signal.upper()],
            }
            for signal in SIGNALS
        ] + [
            {
                "code": code,
                "family": "DIVERGENCE",
                "direction": direction,
                "full_count": full_counts[code],
                "display_count": shown[code],
            }
            for code, _, direction in DIVERGENCE_SIGNALS
        ] + [
            {
                "code": code,
                "family": "DELTA",
                "direction": "BUY" if code == "DELTA_LOW" else "SELL",
                "full_count": full_counts[code],
                "display_count": shown[code],
            }
            for code in DELTA_SIGNALS
        ]

    def calculate_all(self, dataset_id: str):
        """Calculate the full-history event stream shared by preview and replay."""
        bars, dataset = self.catalog.read(dataset_id)
        if dataset["timeframe"] != "1d":
            raise ValueError("signal preview requires daily bars")

        calculated = self.gpma.calculate(bars).copy().reset_index(drop=True)
        calculated["date"] = pd.to_datetime(calculated.date)
        dates = calculated.date.dt.date.tolist()
        events: list[dict] = []
        full_counts: dict[str, int] = {}

        for signal in SIGNALS:
            code = signal.upper()
            direction = "BUY" if signal in BUY_SIGNALS else "SELL"
            indexes = [int(index) for index, active in calculated[signal].items() if bool(active)]
            full_counts[code] = len(indexes)
            for index in indexes:
                signal_date = dates[index].isoformat()
                events.append({
                    "code": code,
                    "family": "B" if direction == "BUY" else "S",
                    "direction": direction,
                    "signal_date": signal_date,
                    "marker_date": signal_date,
                    "tradable_on": dates[index + 1].isoformat() if index + 1 < len(dates) else None,
                    "actual_date": signal_date,
                    "confirmed_on": signal_date,
                    "price": float(calculated.low.iloc[index] if direction == "BUY" else calculated.high.iloc[index]),
                    "structure_price": None,
                })

        for code, column, direction in DIVERGENCE_SIGNALS:
            # The *_y columns are the final DRAWICON conditions after the
            # engine's de-duplication and candle/EMA filters.  The raw
            # top_1/bottom_1/top_2/bottom_2 flags are intentionally not used.
            indexes = [
                int(index)
                for index, marker_y in calculated[column].items()
                if pd.notna(marker_y)
            ]
            full_counts[code] = len(indexes)
            for index in indexes:
                signal_date = dates[index].isoformat()
                events.append({
                    "code": code,
                    "family": "DIVERGENCE",
                    "direction": direction,
                    "signal_date": signal_date,
                    "marker_date": signal_date,
                    "tradable_on": dates[index + 1].isoformat() if index + 1 < len(dates) else None,
                    "actual_date": signal_date,
                    "confirmed_on": signal_date,
                    "price": float(calculated[column].iloc[index]),
                    "structure_price": None,
                })

        delta_analysis = self.delta.analyze(bars)
        delta_counts = {code: 0 for code in DELTA_SIGNALS}
        date_positions = {value.isoformat(): index for index, value in enumerate(dates)}
        for point in delta_analysis.get("confirmed_points", []):
            tradable_on = point.get("tradable_on")
            if not tradable_on or tradable_on not in date_positions:
                continue
            event_type = str(point["type"]).upper()
            code = f"DELTA_{event_type}"
            if code not in delta_counts:
                continue
            index = date_positions[tradable_on]
            direction = "BUY" if event_type == "LOW" else "SELL"
            delta_counts[code] += 1
            events.append({
                "code": code,
                "family": "DELTA",
                "direction": direction,
                "signal_date": point["actual_date"],
                "marker_date": tradable_on,
                "tradable_on": tradable_on,
                "actual_date": point["actual_date"],
                "confirmed_on": point.get("confirmed_on"),
                "price": float(calculated.low.iloc[index] if direction == "BUY" else calculated.high.iloc[index]),
                "structure_price": float(point["price"]),
            })
        full_counts.update(delta_counts)

        return calculated, dataset, events, full_counts, delta_analysis

    def build(self, dataset_id: str, years: int = 2) -> dict:
        if years not in {1, 2}:
            raise ValueError("preview years must be 1 or 2")
        calculated, dataset, events, full_counts, delta_analysis = self.calculate_all(dataset_id)
        delta_counts = {
            code: full_counts.get(code, 0)
            for code in DELTA_SIGNALS
        }

        display_end = calculated.date.iloc[-1]
        display_start = display_end - pd.DateOffset(years=years)
        display = calculated.loc[calculated.date >= display_start]
        display_start_date = display.date.iloc[0].date().isoformat()
        display_end_date = display.date.iloc[-1].date().isoformat()
        visible_events = [
            event for event in events
            if display_start_date <= event["marker_date"] <= display_end_date
        ]
        display_counts = {
            code: sum(event["code"] == code for event in visible_events)
            for code in (
                *[signal.upper() for signal in SIGNALS],
                *[code for code, _, _ in DIVERGENCE_SIGNALS],
                *DELTA_SIGNALS,
            )
        }
        signal_catalog = self.describe_signals(full_counts, display_counts)

        return {
            "dataset": dataset,
            "range": {
                "years": years,
                "start": display_start_date,
                "end": display_end_date,
                "display_bar_count": len(display),
                "full_bar_count": len(calculated),
            },
            "bars": [self._bar(row) for row in display.itertuples(index=False)],
            "signal_catalog": signal_catalog,
            "events": visible_events,
            "delta": {
                "status": delta_analysis.get("status"),
                "history_confidence": delta_analysis.get("history_confidence"),
                "confirmed_point_count": sum(delta_counts.values()),
            },
            "assumptions": {
                "indicator_signal": "signal is known after its session close",
                "indicator_tradable_on": "next available session",
                "divergence_signal": "final filtered DRAWICON point is known after its session close",
                "delta_marker": "confirmed DELTA point is plotted on tradable_on, never on the retrospective extreme date",
                "calculation": "signals are calculated on full history before the display range is sliced",
            },
        }
