import pandas as pd

from app.services.gpmapro_trace import TraceSnapshotService


def test_trace_snapshot_is_immutable_and_reports_field_level_differences(tmp_path):
    service = TraceSnapshotService(tmp_path)
    manifest = service.import_frame(pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "E8": [10., 11.], "TBL1": [False, True]}))
    trace, loaded = service.load(manifest["trace_id"])
    assert loaded["content_sha256"] == manifest["content_sha256"]
    local = pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "E8": [10., 11.2], "TBL1": [False, False]})
    comparison = service.compare(local, trace)
    assert comparison["overlap_rows"] == 2
    assert comparison["fields"]["E8"]["mismatched"] == 1
    assert comparison["fields"]["TBL1"]["mismatched"] == 1
