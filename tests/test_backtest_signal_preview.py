import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.services.backtest_signal_preview import (
    BacktestSignalPreviewService,
    DIVERGENCE_SIGNALS,
)
from app.services.gpmaapro_engine import SIGNALS


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


class FakeGpma:
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        for signal in SIGNALS:
            result[signal] = False
        for _, column, _ in DIVERGENCE_SIGNALS:
            result[column] = float("nan")
        result.loc[[0, len(result) - 10], "b11"] = True
        result.loc[len(result) - 5, "s12"] = True
        result.loc[[1, len(result) - 9], "bottom_1_y"] = result.loc[
            [1, len(result) - 9], "low"
        ]
        result.loc[len(result) - 8, "top_1_y"] = result.loc[len(result) - 8, "high"]
        result.loc[len(result) - 7, "bottom_2_y"] = result.loc[len(result) - 7, "low"]
        result.loc[len(result) - 6, "top_2_y"] = result.loc[len(result) - 6, "high"]
        return result


class FakeDelta:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def analyze(self, _frame: pd.DataFrame) -> dict:
        dates = self.frame.date.tolist()
        return {
            "status": "READY",
            "history_confidence": "LIMITED",
            "confirmed_points": [{
                "id": "delta-test-low",
                "type": "LOW",
                "actual_date": dates[-20],
                "confirmed_on": dates[-15],
                "tradable_on": dates[-14],
                "price": float(self.frame.low.iloc[-20]),
            }],
        }


def test_signal_preview_calculates_full_history_before_slicing_display_range():
    frame = bars()
    result = BacktestSignalPreviewService(
        FakeCatalog(frame), gpma=FakeGpma(), delta=FakeDelta(frame)
    ).build("local_csv:US.TEST", years=1)

    catalog = {item["code"]: item for item in result["signal_catalog"]}
    assert result["range"]["full_bar_count"] == 600
    assert 250 <= result["range"]["display_bar_count"] <= 263
    assert catalog["B11"]["full_count"] == 2
    assert catalog["B11"]["display_count"] == 1
    assert catalog["S12"]["display_count"] == 1
    assert catalog["BOTTOM_FACE"]["full_count"] == 2
    assert catalog["BOTTOM_FACE"]["display_count"] == 1
    assert catalog["TOP_FACE"]["display_count"] == 1
    assert catalog["BOTTOM_ARROW_2"]["display_count"] == 1
    assert catalog["TOP_ARROW_2"]["display_count"] == 1
    assert set(catalog) == {
        *(signal.upper() for signal in SIGNALS),
        *(code for code, _, _ in DIVERGENCE_SIGNALS),
        "DELTA_LOW",
        "DELTA_HIGH",
    }


def test_divergence_preview_uses_final_drawicon_columns_and_next_session():
    frame = bars()
    result = BacktestSignalPreviewService(
        FakeCatalog(frame), gpma=FakeGpma(), delta=FakeDelta(frame)
    ).build("local_csv:US.TEST", years=2)

    event = next(item for item in result["events"] if item["code"] == "BOTTOM_FACE")
    expected_index = len(frame) - 9
    assert event["family"] == "DIVERGENCE"
    assert event["direction"] == "BUY"
    assert event["signal_date"] == frame.date.iloc[expected_index]
    assert event["marker_date"] == frame.date.iloc[expected_index]
    assert event["tradable_on"] == frame.date.iloc[expected_index + 1]
    assert event["price"] == frame.low.iloc[expected_index]


def test_delta_preview_marks_the_confirmed_tradable_date_not_the_extreme_date():
    frame = bars()
    result = BacktestSignalPreviewService(
        FakeCatalog(frame), gpma=FakeGpma(), delta=FakeDelta(frame)
    ).build("local_csv:US.TEST", years=2)

    event = next(item for item in result["events"] if item["code"] == "DELTA_LOW")
    assert event["signal_date"] == frame.date.iloc[-20]
    assert event["actual_date"] == frame.date.iloc[-20]
    assert event["confirmed_on"] == frame.date.iloc[-15]
    assert event["marker_date"] == frame.date.iloc[-14]
    assert event["tradable_on"] == frame.date.iloc[-14]
    assert event["marker_date"] != event["actual_date"]


def test_signal_preview_rejects_ranges_outside_one_or_two_years():
    frame = bars()
    service = BacktestSignalPreviewService(
        FakeCatalog(frame), gpma=FakeGpma(), delta=FakeDelta(frame)
    )

    try:
        service.build("local_csv:US.TEST", years=3)
    except ValueError as error:
        assert "1 or 2" in str(error)
    else:
        raise AssertionError("unsupported preview ranges must be rejected")


def test_signal_preview_api_returns_the_chart_contract(monkeypatch):
    from app.api import backtest_datasets as dataset_api

    frame = bars()
    service = BacktestSignalPreviewService(
        FakeCatalog(frame), gpma=FakeGpma(), delta=FakeDelta(frame)
    )
    monkeypatch.setattr(dataset_api, "preview_service", service)

    response = TestClient(app).post(
        "/api/backtest/datasets/signal-preview",
        json={"dataset_id": "local_csv:US.TEST", "years": 1},
    )

    assert response.status_code == 200
    assert {"dataset", "range", "bars", "signal_catalog", "events", "delta", "assumptions"} == set(response.json())
