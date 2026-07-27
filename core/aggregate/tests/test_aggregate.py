import numpy as np
import pandas as pd

from ..aggregate import aggregate_events


def test_aggregate_yields_known_dense_counts(located_events_simple):
    aggregate = aggregate_events(
        located_events_simple, event_type="infections", days_per_bin=1.0
    )

    # Columns are the sorted distinct geo units.
    assert list(aggregate.geo_unit_ids) == [10, 20]
    # Two day-wide bins starting at 0 and 1.
    assert list(aggregate.bin_starts) == [0.0, 1.0]

    # Rows = bins, columns = geo units.
    expected = np.array(
        [
            [2, 1],  # day 0: geo 10 x2, geo 20 x1
            [1, 2],  # day 1: geo 10 x1, geo 20 x2
        ]
    )
    np.testing.assert_array_equal(aggregate.counts, expected)
    assert aggregate.event_type == "infections"


def test_event_type_label_propagates(located_events_simple):
    aggregate = aggregate_events(located_events_simple, event_type="deaths")
    assert aggregate.event_type == "deaths"


def test_rows_without_geo_unit_are_dropped():
    # A NaN geo_unit_id (an unresolved source in load_geo_events) drops the row
    # rather than crashing.
    events = pd.DataFrame(
        {
            "time": [0.2, 0.5, 1.3],
            "geo_unit_id": [7.0, np.nan, 9.0],
        }
    )
    aggregate = aggregate_events(events, event_type="deaths", days_per_bin=1.0)
    assert list(aggregate.geo_unit_ids) == [7, 9]
    np.testing.assert_array_equal(aggregate.counts, np.array([[1, 0], [0, 1]]))


def test_time_bins_are_half_open_and_windowed():
    # Events on exact day boundaries; days_per_bin=2, window [0, 4).
    events = pd.DataFrame(
        {
            "time": [0.0, 1.0, 2.0, 3.0, 4.0],
            "geo_unit_id": [5, 5, 5, 5, 5],
        }
    )
    aggregate = aggregate_events(
        events,
        event_type="infections",
        days_per_bin=2.0,
        time_start=0.0,
        time_end=4.0,
    )
    # bin0 = [0, 2): times 0.0, 1.0 ; bin1 = [2, 4): times 2.0, 3.0 ;
    # time 4.0 == time_end is excluded (half-open).
    assert list(aggregate.bin_starts) == [0.0, 2.0]
    np.testing.assert_array_equal(aggregate.counts, np.array([[2], [2]]))
