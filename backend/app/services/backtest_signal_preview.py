"""Signal-enriched OHLCV preview for the new backtest laboratory."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.services.gpmaapro_engine import GpmaAproEngine, SIGNALS as V2_SIGNAL_COLUMNS
from app.services.gpmapro_engine import GpmaProEngine


V1_SIGNAL_COLUMNS = ("b1", "b2", "b3", "s1", "s2")


@dataclass(frozen=True)
class SignalDefinition:
    code: str
    column: str
    version: str
    family: str
    direction: str


def _indicator_definitions(
    version: str,
    columns: tuple[str, ...],
    aliases: dict[str, str] | None = None,
) -> tuple[SignalDefinition, ...]:
    names = aliases or {}
    return tuple(
        SignalDefinition(
            code=f"V{version[0]}_{names.get(column, column).upper()}",
            column=column,
            version=version,
            family="B" if column.startswith("b") else "S",
            direction="BUY" if column.startswith("b") else "SELL",
        )
        for column in columns
    )


SIGNAL_DEFINITIONS = (
    *_indicator_definitions("1.0", V1_SIGNAL_COLUMNS),
    SignalDefinition("V1_BOTTOM_FACE", "bottom_face_y", "1.0", "DIVERGENCE", "BUY"),
    SignalDefinition("V1_TOP_FACE", "top_face_y", "1.0", "DIVERGENCE", "SELL"),
    SignalDefinition("V1_BOTTOM_ARROW_2", "bottom_arrow_2_y", "1.0", "DIVERGENCE", "BUY"),
    SignalDefinition("V1_TOP_ARROW_2", "top_arrow_2_y", "1.0", "DIVERGENCE", "SELL"),
    SignalDefinition("V1_BOTTOM_ARROW_3", "bottom_arrow_3_y", "1.0", "DIVERGENCE", "BUY"),
    SignalDefinition("V1_TOP_ARROW_3", "top_arrow_3_y", "1.0", "DIVERGENCE", "SELL"),
    *_indicator_definitions("2.0", V2_SIGNAL_COLUMNS, {"b3": "b031", "s2": "s021"}),
)


class BacktestSignalPreviewService:
    def __init__(self, catalog, gpma_v1=None, gpma_v2=None):
        self.catalog = catalog
        self.gpma_v1 = gpma_v1 or GpmaProEngine()
        self.gpma_v2 = gpma_v2 or GpmaAproEngine()

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
                "code": definition.code,
                "version": definition.version,
                "family": definition.family,
                "direction": definition.direction,
                "full_count": full_counts[definition.code],
                "display_count": shown[definition.code],
            }
            for definition in SIGNAL_DEFINITIONS
        ]

    def calculate_all(self, dataset_id: str):
        """Calculate the full-history event stream shared by preview and replay."""
        bars, dataset = self.catalog.read(dataset_id)
        if dataset["timeframe"] != "1d":
            raise ValueError("signal preview requires daily bars")

        calculated_by_version = {
            "1.0": self.gpma_v1.calculate(bars).copy().reset_index(drop=True),
            "2.0": self.gpma_v2.calculate(bars).copy().reset_index(drop=True),
        }
        for calculated_version in calculated_by_version.values():
            calculated_version["date"] = pd.to_datetime(calculated_version.date)
        calculated = calculated_by_version["2.0"]
        if not calculated_by_version["1.0"].date.equals(calculated.date):
            raise ValueError("GPMAPRO 1.0 and 2.0 produced different trading calendars")
        dates = calculated.date.dt.date.tolist()
        events: list[dict] = []
        full_counts: dict[str, int] = {}

        for definition in SIGNAL_DEFINITIONS:
            version_data = calculated_by_version[definition.version]
            if definition.family == "DIVERGENCE":
                # Use each formula's final DRAWICON coordinate rather than a
                # raw intermediate condition, preserving its own filters.
                indexes = [
                    int(index)
                    for index, marker_y in version_data[definition.column].items()
                    if pd.notna(marker_y)
                ]
            else:
                indexes = [
                    int(index)
                    for index, active in version_data[definition.column].items()
                    if bool(active)
                ]
            full_counts[definition.code] = len(indexes)
            for index in indexes:
                signal_date = dates[index].isoformat()
                events.append({
                    "code": definition.code,
                    "version": definition.version,
                    "family": definition.family,
                    "direction": definition.direction,
                    "signal_date": signal_date,
                    "marker_date": signal_date,
                    "tradable_on": dates[index + 1].isoformat() if index + 1 < len(dates) else None,
                    "actual_date": signal_date,
                    "confirmed_on": signal_date,
                    "price": float(
                        version_data[definition.column].iloc[index]
                        if definition.family == "DIVERGENCE"
                        else version_data.low.iloc[index]
                        if definition.direction == "BUY"
                        else version_data.high.iloc[index]
                    ),
                    "structure_price": None,
                })

        return calculated, dataset, events, full_counts

    def build(self, dataset_id: str, years: int = 2) -> dict:
        if years not in {1, 2}:
            raise ValueError("preview years must be 1 or 2")
        calculated, dataset, events, full_counts = self.calculate_all(dataset_id)

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
            for code in (definition.code for definition in SIGNAL_DEFINITIONS)
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
            "assumptions": {
                "indicator_signal": "signal is known after its session close",
                "indicator_tradable_on": "next available session",
                "divergence_signal": "each formula version uses its final filtered DRAWICON point after session close",
                "calculation": "GPMAPRO 1.0 and 2.0 are calculated on the same full history before display slicing",
            },
        }
