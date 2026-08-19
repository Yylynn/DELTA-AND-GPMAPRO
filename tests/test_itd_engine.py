import pandas as pd

from app.quant.delta_time import ITDDeltaEngine, ITD_CALENDAR_DAYS, ITD_TRADING_BARS, MIN_GAP_TRADING_DAYS


def bars(count: int) -> pd.DataFrame:
    dates = pd.date_range("2023-01-02", periods=count, freq="B")
    return pd.DataFrame([
        {"date": day, "open": 100 + i * .1, "high": 101 + i * .1 + i % 7,
         "low": 99 + i * .1 - i % 5, "close": 100.2 + i * .1, "volume": 1_000 + i}
        for i, day in enumerate(dates)
    ])


def test_skill_delta_uses_fixed_118_bar_units_and_four_colours():
    result = ITDDeltaEngine().analyze(bars(310))
    assert result["status"] == "READY"
    assert result["sequence_length"] == 12
    assert result["itd_calendar_days"] == ITD_CALENDAR_DAYS == 171
    assert ITD_TRADING_BARS == 118
    assert [line["color"] for line in result["grid_lines"][:4]] == ["ORANGE", "GREEN", "RED", "BLUE"]
    assert [point["number"] for point in result["points"][:12]] == list(range(1, 13))


def test_points_alternate_and_terminal_point_is_not_confirmed():
    result = ITDDeltaEngine().analyze(bars(310))
    confirmed = result["confirmed_points"]
    assert all(left["type"] != right["type"] for left, right in zip(confirmed, confirmed[1:]))
    assert result["boundary_point"]["confirmed"] is False
    assert result["boundary_point"] in result["candidate_points"]


def test_all_realised_points_respect_the_eight_trading_day_floor():
    result = ITDDeltaEngine().analyze(bars(330))
    points = result["points"]
    assert result["min_gap_trading_days"] == MIN_GAP_TRADING_DAYS == 8
    assert all(right["bar_index"] - left["bar_index"] >= MIN_GAP_TRADING_DAYS for left, right in zip(points, points[1:]))


def test_live_tail_stops_instead_of_creating_a_too_close_next_number():
    # The #8 nominal band has begun by bar 310, but #7 occupies the earliest
    # legal location from which another eight-session gap cannot fit.  #8 must
    # remain a forecast rather than becoming an adjacent false candidate.
    result = ITDDeltaEngine().analyze(bars(310))
    live_numbers = [point["number"] for point in result["points"] if point["cycle"] == 3]
    assert live_numbers == list(range(1, 8))
    assert result["boundary_point"]["number"] == 7
    assert result["future_predictions"][1]["number"] == 8


def test_short_historical_average_is_clamped_to_eight_trading_days():
    trading_dates = [day.date() for day in pd.bdate_range("2024-01-01", periods=30)]
    history = [
        {"number": 1, "date": "2024-01-01"},
        {"number": 2, "date": "2024-01-02"},
        {"number": 3, "date": "2024-01-03"},
    ]
    anchor = {"number": 2, "date": "2024-01-02", "type": "LOW"}
    prediction = ITDDeltaEngine._forecast(anchor, history, pd.Timestamp("2024-01-02").date(), trading_dates, steps=1)[0]
    assert prediction["constraint_applied"] is True
    assert prediction["expected_date"] == prediction["min_gap_earliest_date"]
    assert prediction["expected_date"] == "2024-01-12"


def test_current_candidate_window_is_refreshed_to_its_stock_boundary_date():
    trading_dates = [day.date() for day in pd.bdate_range("2024-01-01", periods=40)]
    history = [
        {"number": 1, "date": "2024-01-01"},
        {"number": 2, "date": "2024-01-02"},
        {"number": 3, "date": "2024-01-03"},
    ]
    boundary = {"id": "candidate-3", "number": 3, "type": "HIGH", "date": "2024-01-25"}
    prediction = ITDDeltaEngine._current_boundary_prediction(boundary, history, trading_dates)
    assert prediction["candidate_window_rebased"] is True
    assert prediction["expected_date"] == boundary["date"]
    assert prediction["lo_date"] <= boundary["date"] <= prediction["hi_date"]


def test_two_predictions_are_chained_from_current_boundary_after_real_history():
    result = ITDDeltaEngine().analyze(bars(310))
    first, second = result["future_predictions"]
    anchor = result["boundary_point"]
    last_real_date = bars(310)["date"].iloc[-1].date().isoformat()
    assert len(result["future_predictions"]) == 2
    assert first["number"] == anchor["number"]
    assert first["phase"] == "current_candidate"
    assert first["observed_boundary_date"] == anchor["date"]
    assert second["number"] == first["number"] % 12 + 1
    assert second["expected_date"] > last_real_date
    assert second["expected_date"] >= second["min_gap_earliest_date"]
    assert first["lo_date"] <= first["expected_date"] <= first["hi_date"]


def test_transition_table_covers_one_full_future_number_cycle():
    result = ITDDeltaEngine().analyze(bars(310))
    last_real_date = bars(310)["date"].iloc[-1].date().isoformat()
    assert [row["number"] for row in result["transition_table"]] == list(range(1, 13))
    assert len(result["transition_predictions"]) == 12
    # The first row is the live, unresolved candidate; every following row
    # must be a genuinely future chained event.
    assert all(item["expected_date"] > last_real_date for item in result["transition_predictions"][1:])
    first = result["future_predictions"][0]
    table_row = result["transition_table"][first["number"] - 1]
    assert table_row["prediction"]["expected_date"] == first["expected_date"]


def test_live_unit_number_and_prediction_are_stock_specific_not_forced_to_one():
    # The strict floor leaves a seven-band live tail, which remains dynamic
    # rather than falling back to a fixed #1 forecast.
    first = ITDDeltaEngine().analyze(bars(310))
    assert first["boundary_point"]["number"] == 7
    assert first["future_predictions"][0]["number"] == 7
    assert first["future_predictions"][1]["number"] == 8

    # A longer listing/history is at a different structural position and must
    # consequently expose a different target number.
    second = ITDDeltaEngine().analyze(bars(330))
    assert second["boundary_point"]["number"] == 9
    assert second["future_predictions"][0]["number"] == 9
    assert second["future_predictions"][1]["number"] == 10


def test_incomplete_history_is_not_structured():
    result = ITDDeltaEngine().analyze(bars(117))
    assert result["status"] == "INSUFFICIENT_HISTORY"
    assert not result["points"]
