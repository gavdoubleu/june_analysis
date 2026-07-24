import numpy as np
import pandas as pd

from ..aggregate import aggregate_events


def test_aggregate_yields_known_dense_counts(enriched_events_simple):
    aggregate = aggregate_events(
        enriched_events_simple, event_type="infections", days_per_bin=1.0
    )

    # Columns are the sorted distinct resolved geo units.
    assert list(aggregate.geo_unit_ids) == [10, 20]
    # Two day-wide bins starting at 0 and 1.
    assert list(aggregate.bin_starts) == [0.0, 1.0]

    # Rows = bins, columns = geo units (venue geo resolution).
    expected = np.array(
        [
            [2, 1],  # day 0: geo 10 x2, geo 20 x1
            [1, 2],  # day 1: geo 10 x1, geo 20 x2
        ]
    )
    np.testing.assert_array_equal(aggregate.counts, expected)
    assert aggregate.event_type == "infections"


def test_event_type_label_propagates(enriched_events_simple):
    aggregate = aggregate_events(enriched_events_simple, event_type="deaths")
    assert aggregate.event_type == "deaths"


def test_aggregates_when_venue_geo_column_absent():
    # e.g. an event table with no venue geo at all — resolution falls through
    # geo_priority to the person geo without error.
    events = pd.DataFrame(
        {
            "time": [0.2, 0.5, 1.3],
            "person_geo_unit_id": [7, 7, 9],
        }
    )
    aggregate = aggregate_events(events, event_type="deaths", days_per_bin=1.0)
    assert list(aggregate.geo_unit_ids) == [7, 9]
    np.testing.assert_array_equal(aggregate.counts, np.array([[2, 0], [0, 1]]))


def test_time_bins_are_half_open_and_windowed():
    # Events on exact day boundaries; days_per_bin=2, window [0, 4).
    events = pd.DataFrame(
        {
            "time": [0.0, 1.0, 2.0, 3.0, 4.0],
            "venue_geo_unit_id": [5, 5, 5, 5, 5],
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


def test_person_first_geo_priority_keys_on_residence(enriched_events_simple):
    # In the fixture venue and person geo are deliberately swapped, so the
    # person-first result is the mirror of the venue-first tracer.
    aggregate = aggregate_events(
        enriched_events_simple,
        event_type="deaths",
        geo_priority=("person",),
    )
    assert list(aggregate.geo_unit_ids) == [10, 20]
    np.testing.assert_array_equal(
        aggregate.counts, np.array([[1, 2], [2, 1]])
    )


def test_geo_priority_falls_back_when_first_source_missing():
    # venue geo missing (NaN) on some rows -> coalesce to person geo.
    events = pd.DataFrame(
        {
            "time": [0.1, 0.2, 0.3],
            "venue_geo_unit_id": [np.nan, 30, np.nan],
            "person_geo_unit_id": [40, 50, 40],
        }
    )
    aggregate = aggregate_events(
        events, event_type="infections", geo_priority=("venue", "person")
    )
    # row0 -> 40 (venue NaN), row1 -> 30 (venue wins), row2 -> 40.
    assert list(aggregate.geo_unit_ids) == [30, 40]
    np.testing.assert_array_equal(aggregate.counts, np.array([[1, 2]]))
