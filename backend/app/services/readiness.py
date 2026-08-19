from app.config.dataset_config import DATASET_CONFIG


def readiness(universe: list[dict], diagnostics: dict | None = None) -> dict:
    events = diagnostics or {}
    states = events.get("pooled", {})
    funnel = events.get("delta_funnel", {})
    checks = {
        "eligible_symbols": (sum(x["research_eligibility"] == "ELIGIBLE" for x in universe), DATASET_CONFIG.readiness_eligible_symbols),
        "decision_events": (events.get("total_events", 0), DATASET_CONFIG.readiness_transition_events),
        "buy_events": (states.get("BUY", {}).get("sample_count", 0), DATASET_CONFIG.readiness_buy_events),
        "watch_events": (states.get("WATCH", {}).get("sample_count", 0), DATASET_CONFIG.readiness_watch_events),
        "risk_events": (states.get("RISK", {}).get("sample_count", 0), DATASET_CONFIG.readiness_risk_events),
        "delta_confirmations": (funnel.get("decision_confirmations", 0), DATASET_CONFIG.readiness_delta_confirmations),
    }
    requirements = {key: {"current": current, "required": required, "passed": current >= required} for key, (current, required) in checks.items()}
    return {"status": "READY_FOR_CALIBRATION" if all(x["passed"] for x in requirements.values()) else "NOT_READY", "requirements": requirements}
