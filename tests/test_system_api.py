from fastapi.testclient import TestClient
from app.main import app
def test_health_returns_terminal_identity() -> None:
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "DELTA 时空交易终端"}
def test_version_returns_version_information() -> None:
    response = TestClient(app).get("/api/version")
    assert response.status_code == 200
    assert response.json()["version"] == "0.1.0"


def test_decision_api_has_a_stable_snapshot_schema() -> None:
    response = TestClient(app).get("/api/decision/AAPL?timeframe=1d&as_of=2024-11-29")
    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2024-11-29"
    assert body["state"] in {"BUY", "WATCH", "WAIT", "RISK"}
    assert {"confirmations", "missing_conditions", "risk_factors", "decision_trace"} <= set(body)


def test_decision_backtest_api_schema_and_pagination() -> None:
    client = TestClient(app)
    summary = client.get("/api/backtest/decisions/DEMO?sampling_mode=DAILY")
    assert summary.status_code == 200
    assert {"BUY", "WATCH", "WAIT", "RISK"} == set(summary.json()["states"])
    events = client.get("/api/backtest/decisions/DEMO/events?sampling_mode=DAILY&limit=1")
    assert events.status_code == 200
    assert {"total", "events"} == set(events.json())


def test_diagnostics_api_schema() -> None:
    response = TestClient(app).post("/api/diagnostics/decisions", json={"symbols": ["DEMO"], "sampling_mode": "DAILY"})
    assert response.status_code == 200
    assert {"pooled", "per_symbol", "cross_symbol", "delta_funnel", "robustness_flags"} <= set(response.json())
