import pandas as pd

from app.services.mai_language import MaiRuntime


def test_runtime_ref_barslast_and_dynamic_hhv_are_causal_and_traced():
    index = pd.RangeIndex(6); runtime = MaiRuntime(index)
    values = pd.Series([3., 1., 5., 2., 4., 6.], index=index)
    condition = pd.Series([False, True, False, False, True, False], index=index)
    ages = runtime.barslast(condition, "EVENT_AGE")
    assert ages.tolist()[1:] == [0., 1., 2., 0., 1.]
    assert runtime.ref(values, ages, "VALUE_AT_EVENT").tolist()[1:] == [1., 1., 1., 4., 4.]
    window = runtime.put("WINDOW", ages + 1)
    assert runtime.hhv(values, window, "DYNAMIC_HHV").tolist()[1:] == [1., 5., 5., 4., 6.]
    assert {"EVENT_AGE", "VALUE_AT_EVENT", "WINDOW", "DYNAMIC_HHV"} <= set(runtime.trace)


def test_drawnull_keeps_a_real_gap_instead_of_connecting_colours():
    runtime = MaiRuntime(pd.RangeIndex(4))
    rendered = runtime.drawnull(pd.Series([10., 11., 12., 13.]), pd.Series([True, False, False, True]), "E8R")
    assert rendered.tolist()[0] == 10.
    assert rendered.iloc[1:3].isna().all()
    assert rendered.tolist()[3] == 13.
