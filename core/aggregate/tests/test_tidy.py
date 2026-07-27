import numpy as np

from ..aggregate import aggregate_events
from ..tidy import epidemic_curve, to_long_dataframe


def test_epidemic_curve_sums_over_geo(located_events_simple):
    aggregate = aggregate_events(located_events_simple, event_type="infections")
    curve = epidemic_curve(aggregate)

    assert list(curve.columns) == ["bin_start", "count"]
    assert list(curve["bin_start"]) == [0.0, 1.0]
    # Three events each day, summed over both geo units.
    assert list(curve["count"]) == [3, 3]


def test_to_long_dataframe_is_tidy_and_drops_zero(located_events_simple):
    aggregate = aggregate_events(located_events_simple, event_type="infections")
    frame = to_long_dataframe(aggregate)

    assert list(frame.columns) == ["bin_start", "geo_unit_id", "event_type", "count"]
    # Every (bin, geo) cell here is non-zero: 2 bins x 2 geos = 4 rows.
    assert len(frame) == 4
    assert set(frame["event_type"]) == {"infections"}
    row = frame[(frame["bin_start"] == 0.0) & (frame["geo_unit_id"] == 10)]
    assert int(row["count"].iloc[0]) == 2


def test_to_long_dataframe_selects_only_requested_geos(located_events_simple):
    aggregate = aggregate_events(located_events_simple, event_type="infections")
    frame = to_long_dataframe(aggregate, geo_unit_ids=[20])

    assert set(frame["geo_unit_id"]) == {20}
    np.testing.assert_array_equal(sorted(frame["count"]), [1, 2])
