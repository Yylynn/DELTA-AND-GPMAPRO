import pandas as pd

from app.services.decision_backtest import DecisionBacktestService


def bars(count=45):
    dates = pd.date_range("2025-01-01", periods=count, freq="B")
    close = pd.Series(range(100, 100 + count), dtype=float)
    return pd.DataFrame({"date": dates, "open": close - .5, "high": close + 1, "low": close - 2, "close": close, "volume": [1000] * count})


def event(state="WATCH", confidence=.6, count=1, returned=.02):
    outcome = {str(h): {"forward_return": returned, "mfe": returned + .01, "mae": -.01} for h in (5, 10, 20)}
    return {"state": state, "confidence": confidence, "confirmations": {"delta": count > 0, "trend": False, "signal": False, "volume": False, "historical": False, "count": count}, "confirmation_signature": "DELTA" if count else "NONE", "conflict_count": 0, "outcomes": outcome}


def test_outcome_definition_and_tail_availability():
    service, data = DecisionBacktestService(), bars(25)
    outcome = service._outcomes(data, 0)
    assert outcome["5"]["forward_return"] == data.close.iloc[5] / data.close.iloc[0] - 1
    assert outcome["10"]["mfe"] == data.high.iloc[1:11].max() / data.close.iloc[0] - 1
    assert outcome["10"]["mae"] == data.low.iloc[1:11].min() / data.close.iloc[0] - 1
    assert service._outcomes(data, 21)["5"]["forward_return"] is None


def test_state_stats_keep_horizon_sample_counts_separate():
    short = event(); short["outcomes"]["20"] = {"forward_return": None, "mfe": None, "mae": None}
    stats = DecisionBacktestService()._stats([event(returned=.01), short])
    assert stats["sample_count"] == 2 and stats["sample_count_10"] == 2 and stats["sample_count_20"] == 1
    assert stats["positive_rate_10"] == 1 and stats["sample_quality"] == "LOW_SAMPLE"


def test_breakdowns_cover_confidence_confirmation_delta_and_conflict():
    service = DecisionBacktestService(); events = [event(confidence=.35, count=0), event(confidence=.75, count=2)]
    assert set(service.breakdown(events, "confidence")["groups"]) == {"<0.40", "0.70-0.85"}
    assert set(service.breakdown(events, "confirmations")["groups"]) == {"0", "2"}
    assert set(service.breakdown(events, "delta")["groups"]) == {"true", "false"}
    assert service.breakdown(events, "conflict")["groups"]["0"]["sample_count"] == 2


def test_daily_and_transition_sampling_and_determinism():
    # A real replay exercises Evidence(as_of) -> Decision(as_of) for every bar.
    service, data = DecisionBacktestService(), bars()
    daily = service.replay(data, "X", "1d", sampling_mode="DAILY")
    transition = service.replay(data, "X", "1d", sampling_mode="TRANSITION")
    assert len(daily) == len(data) and len(transition) <= len(daily)
    assert daily == service.replay(data, "X", "1d", sampling_mode="DAILY")


def test_future_mutation_does_not_change_decision_events_before_cutoff():
    service, source = DecisionBacktestService(), bars(55); cutoff = "2025-02-20"
    expected = service.replay(source, "X", "1d", end_date=cutoff, sampling_mode="DAILY")
    changed = source.copy(); changed.loc[changed.date > pd.Timestamp(cutoff), ["open", "high", "low", "close", "volume"]] *= 20
    actual = service.replay(changed, "X", "1d", end_date=cutoff, sampling_mode="DAILY")
    for left, right in zip(expected, actual):
        assert {key: left[key] for key in left if key != "outcomes"} == {key: right[key] for key in right if key != "outcomes"}
