import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.services.backtest_signal_preview import (
    BacktestSignalPreviewService,
    SIGNAL_DEFINITIONS,
)


def bars(count: int = 600) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-03", periods=count)
    close = pd.Series(range(count), dtype=float) / 20 + 100
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close + .25,
        "volume": 1_000,
    })


class FakeCatalog:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def read(self, dataset_id: str):
        return self.frame.copy(), {
            "dataset_id": dataset_id,
            "source": "local_csv",
            "symbol": "US.TEST",
            "timeframe": "1d",
            "bar_count": len(self.frame),
            "data_sha256": "abc",
        }


def blank_calculation(frame: pd.DataFrame, version: str) -> pd.DataFrame:
    result = frame.copy()
    for definition in SIGNAL_DEFINITIONS:
        if definition.version != version:
            continue
        result[definition.column] = (
            float("nan") if definition.family == "DIVERGENCE" else False
        )
    return result


class FakeGpmaV1:
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = blank_calculation(frame, "1.0")
        result.loc[[0, len(result) - 11], "b1"] = True
        result.loc[len(result) - 4, "s2"] = True
        result.loc[len(result) - 10, "bottom_face_y"] = result.loc[len(result) - 10, "low"]
        result.loc[len(result) - 9, "top_face_y"] = result.loc[len(result) - 9, "high"]
        result.loc[len(result) - 8, "bottom_arrow_2_y"] = result.loc[len(result) - 8, "low"]
        result.loc[len(result) - 7, "top_arrow_2_y"] = result.loc[len(result) - 7, "high"]
        result.loc[len(result) - 6, "bottom_arrow_3_y"] = result.loc[len(result) - 6, "low"]
        result.loc[len(result) - 5, "top_arrow_3_y"] = result.loc[len(result) - 5, "high"]
        return result


class FakeGpmaV2:
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = blank_calculation(frame, "2.0")
        result.loc[[0, len(result) - 10], "b11"] = True
        result.loc[len(result) - 9, "b3"] = True
        result.loc[len(result) - 4, "s2"] = True
        result.loc[len(result) - 5, "s12"] = True
        result.loc[[1, len(result) - 9], "bottom_1_y"] = result.loc[
            [1, len(result) - 9], "low"
        ]
        result.loc[len(result) - 8, "top_1_y"] = result.loc[len(result) - 8, "high"]
        result.loc[len(result) - 7, "bottom_2_y"] = result.loc[len(result) - 7, "low"]
        result.loc[len(result) - 6, "top_2_y"] = result.loc[len(result) - 6, "high"]
        return result


def preview_service(frame: pd.DataFrame) -> BacktestSignalPreviewService:
    return BacktestSignalPreviewService(
        FakeCatalog(frame),
        gpma_v1=FakeGpmaV1(),
        gpma_v2=FakeGpmaV2(),
    )


def test_signal_preview_calculates_full_history_before_slicing_display_range():
    frame = bars()
    result = preview_service(frame).build("local_csv:US.TEST", years=1)

    catalog = {item["code"]: item for item in result["signal_catalog"]}
    assert result["range"]["full_bar_count"] == 600
    assert 250 <= result["range"]["display_bar_count"] <= 263
    assert catalog["V1_B1"]["full_count"] == 2
    assert catalog["V1_B1"]["display_count"] == 1
    assert catalog["V1_BOTTOM_ARROW_3"]["display_count"] == 1
    assert catalog["V2_B11"]["full_count"] == 2
    assert catalog["V2_B11"]["display_count"] == 1
    assert catalog["V2_B031"]["display_count"] == 1
    assert catalog["V2_S021"]["display_count"] == 1
    assert catalog["V2_S12"]["display_count"] == 1
    assert catalog["V1_BOTTOM_FACE"]["full_count"] == 1
    assert catalog["V1_BOTTOM_FACE"]["display_count"] == 1
    assert "V2_BOTTOM_FACE" not in catalog
    assert "V2_BOTTOM_ARROW_2" not in catalog
    assert "V2_S2" not in catalog
    assert set(catalog) == {definition.code for definition in SIGNAL_DEFINITIONS}
    assert {item["version"] for item in catalog.values()} == {"1.0", "2.0"}


def test_divergence_preview_uses_final_drawicon_columns_and_next_session():
    frame = bars()
    result = preview_service(frame).build("local_csv:US.TEST", years=2)

    event = next(item for item in result["events"] if item["code"] == "V1_BOTTOM_FACE")
    expected_index = len(frame) - 10
    assert event["family"] == "DIVERGENCE"
    assert event["version"] == "1.0"
    assert event["direction"] == "BUY"
    assert event["signal_date"] == frame.date.iloc[expected_index]
    assert event["marker_date"] == frame.date.iloc[expected_index]
    assert event["tradable_on"] == frame.date.iloc[expected_index + 1]
    assert event["price"] == frame.low.iloc[expected_index]


def test_signal_preview_rejects_ranges_outside_one_or_two_years():
    frame = bars()
    service = preview_service(frame)

    try:
        service.build("local_csv:US.TEST", years=3)
    except ValueError as error:
        assert "1 or 2" in str(error)
    else:
        raise AssertionError("unsupported preview ranges must be rejected")


def test_signal_preview_api_returns_the_chart_contract(monkeypatch):
    from app.api import backtest_datasets as dataset_api

    frame = bars()
    service = preview_service(frame)
    monkeypatch.setattr(dataset_api, "preview_service", service)

    response = TestClient(app).post(
        "/api/backtest/datasets/signal-preview",
        json={"dataset_id": "local_csv:US.TEST", "years": 1},
    )

    assert response.status_code == 200
    assert {"dataset", "range", "bars", "signal_catalog", "events", "assumptions"} == set(response.json())
