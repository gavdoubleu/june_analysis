"""Behaviour of the **Rollup** rewrite (CONTEXT glossary).

Bins-to-bins like `test_trailing_window.py`: each test builds an `Aggregate` and
its ancestor map by hand, so it owns its expected answers. The map is a plain
dict — the same seam `rate_per_100k` takes population over (ADR-0003).
"""

import numpy as np

from ..aggregate import Aggregate
from ..rollup import rollup


def build_aggregate(counts, geo_unit_ids, *, days_per_bin=1.0, time_start=0.0):
    """An `Aggregate` over hand-written counts keyed on `geo_unit_ids`."""
    counts = np.asarray(counts)
    n_bins = counts.shape[0]
    return Aggregate(
        counts=counts,
        geo_unit_ids=np.asarray(geo_unit_ids, dtype="int64"),
        bin_starts=time_start + np.arange(n_bins) * days_per_bin,
        days_per_bin=days_per_bin,
        event_type="infections",
    )


def test_columns_sharing_an_ancestor_are_summed_into_one():
    # The whole point: two areas of one region become that region's column.
    # Columns differ per bin so a transposed or mis-indexed sum cannot pass.
    aggregate = build_aggregate([[1, 2], [30, 40]], [20, 30])

    rolled = rollup(aggregate, {20: 10, 30: 10})

    np.testing.assert_array_equal(rolled.geo_unit_ids, [10])
    np.testing.assert_array_equal(rolled.counts, [[3], [70]])


def test_columns_come_out_sorted_by_id_whatever_order_the_ancestors_arrive_in():
    # `aggregate_events` keys columns via np.unique, so its output is sorted
    # ascending; a rolled Aggregate must be interchangeable with one. Here the
    # ancestors arrive descending, so a naive first-seen ordering would leave
    # column 0 as region 90 and every downstream id lookup off by a column.
    aggregate = build_aggregate([[1, 2, 4]], [20, 30, 40])

    rolled = rollup(aggregate, {20: 90, 30: 90, 40: 10})

    np.testing.assert_array_equal(rolled.geo_unit_ids, [10, 90])
    np.testing.assert_array_equal(rolled.counts, [[4, 3]])


def test_integer_counts_stay_integer_and_windowed_floats_stay_float():
    # Counts are exact integers and must not silently become floats that a CSV
    # export writes as "3.0"; equally, a post-`trailing_mean` Aggregate holds
    # means, and truncating those to int would be a wrong number, not a format.
    integer_aggregate = build_aggregate(np.array([[1, 2]], dtype="int64"), [20, 30])
    float_aggregate = build_aggregate(np.array([[0.5, 2.25]], dtype="float64"), [20, 30])

    ancestors = {20: 10, 30: 10}

    assert rollup(integer_aggregate, ancestors).counts.dtype == np.int64
    rolled_floats = rollup(float_aggregate, ancestors)
    assert rolled_floats.counts.dtype == np.float64
    np.testing.assert_allclose(rolled_floats.counts, [[2.75]])


def test_everything_except_the_geo_keying_survives_untouched():
    # A Rollup is a *geo* rewrite: it must not move the time axis or relabel the
    # event type. Losing `window_days` in particular would make a 7-day mean
    # claim to be a daily count.
    aggregate = Aggregate(
        counts=np.array([[1, 2], [3, 4]]),
        geo_unit_ids=np.array([20, 30]),
        bin_starts=np.array([100.0, 102.0]),
        days_per_bin=2.0,
        event_type="deaths",
        window_days=6.0,
    )

    rolled = rollup(aggregate, {20: 10, 30: 10})

    np.testing.assert_allclose(rolled.bin_starts, [100.0, 102.0])
    assert rolled.days_per_bin == 2.0
    assert rolled.event_type == "deaths"
    assert rolled.window_days == 6.0


def test_a_rollup_loses_no_events():
    # The invariant the whole design protects: coarsening moves counts between
    # columns, it never discards them, so a national total is trustworthy.
    counts = np.arange(12).reshape(3, 4)
    aggregate = build_aggregate(counts, [20, 30, 40, 50])

    rolled = rollup(aggregate, {20: 10, 30: 10, 40: 11, 50: 11})

    assert rolled.counts.sum() == counts.sum()


def test_rolling_to_the_level_an_aggregate_already_keys_on_changes_nothing():
    # Every unit maps to itself at its native level. If self-mapped units were
    # treated as unplaceable and excluded, this would empty the Aggregate.
    counts = np.array([[1, 2], [3, 4]])
    aggregate = build_aggregate(counts, [20, 30])

    rolled = rollup(aggregate, {20: 20, 30: 30})

    np.testing.assert_array_equal(rolled.geo_unit_ids, [20, 30])
    np.testing.assert_array_equal(rolled.counts, counts)


def test_a_column_the_map_has_no_entry_for_survives_under_its_own_id():
    # `World.ancestor_by_geo_unit` omits anything with no ancestor at the level,
    # so an Aggregate routinely carries ids the map does not hold. Raising, or
    # dropping the column, would make a national total silently wrong.
    aggregate = build_aggregate([[1, 2]], [20, 70])

    rolled = rollup(aggregate, {20: 10})

    np.testing.assert_array_equal(rolled.geo_unit_ids, [10, 70])
    np.testing.assert_array_equal(rolled.counts, [[1, 2]])


def test_all_unplaceable_columns_are_reported_in_one_warning(caplog):
    # Silence would let a whole ragged branch sit at the wrong level unnoticed;
    # one message per unit would be thousands of lines on a real run, which
    # nobody reads. One message, naming every id.
    aggregate = build_aggregate([[1, 2, 4, 8]], [-1, 20, 70, 999])

    with caplog.at_level("WARNING"):
        rollup(aggregate, {20: 10})

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "3" in message
    assert "[-1, 70, 999]" in message


def test_a_rollup_where_everything_places_says_nothing(caplog):
    # Including the native-level case: a unit mapped to *itself* is placed, not
    # unplaceable, so a warning keyed on "id unchanged" would cry wolf on every
    # identity rollup and train readers to ignore the message.
    aggregate = build_aggregate([[1, 2]], [20, 30])

    with caplog.at_level("WARNING"):
        rollup(aggregate, {20: 20, 30: 30})

    assert caplog.records == []


def test_unplaceable_columns_stay_distinct_and_keep_every_event():
    # -1 (a seed or foreign-travel event), an orphan and an id absent from the
    # World file are three different things. Merging them into one "unknown"
    # bucket would destroy information, and dropping them would lose 13 events
    # from what a reader will treat as a national total.
    aggregate = build_aggregate([[1, 2, 4, 8]], [-1, 20, 70, 999])

    rolled = rollup(aggregate, {20: 10})

    np.testing.assert_array_equal(rolled.geo_unit_ids, [-1, 10, 70, 999])
    np.testing.assert_array_equal(rolled.counts, [[1, 2, 4, 8]])
    assert rolled.counts.sum() == aggregate.counts.sum()
