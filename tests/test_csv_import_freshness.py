import pandas as pd

from app.data.providers import CsvDataProvider


def csv(dates):
    return pd.DataFrame({"date": dates, "open": [10] * len(dates), "high": [11] * len(dates), "low": [9] * len(dates), "close": [10] * len(dates), "volume": [100] * len(dates)}).to_csv(index=False).encode()


def test_import_reports_new_bars_and_unchanged_latest_date(tmp_path):
    provider = CsvDataProvider(tmp_path); _, first = provider.save("AAPL", csv(["2026-01-01", "2026-01-02"])); assert first["new_bars"] == 2
    _, updated = provider.save("AAPL", csv(["2026-01-01", "2026-01-02", "2026-01-03"])); assert updated["new_bars"] == 1 and updated["import_status"] == "UPDATED"
    _, unchanged = provider.save("AAPL", csv(["2026-01-01", "2026-01-03"])); assert unchanged["new_bars"] == 0 and unchanged["import_status"] == "UNCHANGED"


def test_older_import_is_not_allowed_to_overwrite_current_data(tmp_path):
    provider = CsvDataProvider(tmp_path); provider.save("AAPL", csv(["2026-01-01", "2026-01-03"]))
    data, report = provider.save("AAPL", csv(["2026-01-01", "2026-01-02"]))
    assert report["import_status"] == "REJECTED_OLDER" and str(data.date.iloc[-1]) == "2026-01-03"
