"""Behaviour of the *Trailing window* rewrite (CONTEXT glossary).

Bins-to-bins, unlike `test_aggregate.py`'s events-to-bins: each test builds an
`Aggregate` by hand so it owns its expected answers, then asserts what
`trailing_mean` makes of it.
"""

import numpy as np
import pytest

from ..aggregate import Aggregate
from ..trailing_window import trailing_mean


def build_aggregate(counts, *, days_per_bin=1.0, time_start=0.0):
    """An `Aggregate` over hand-written counts, bins anchored at ``time_start``."""
    counts = np.asarray(counts)
    n_bins = counts.shape[0]
    return Aggregate(
        counts=counts,
        geo_unit_ids=np.arange(counts.shape[1]) * 10,
        bin_starts=time_start + np.arange(n_bins) * days_per_bin,
        days_per_bin=days_per_bin,
        event_type="infections",
    )


def test_each_bin_becomes_the_mean_over_its_trailing_window():
    # Column 0 varies so a wrong window length cannot coincidentally match;
    # column 1 is flat, whose mean must stay 1 whatever the window.
    aggregate = build_aggregate(
        np.array(
            [
                [0, 1], [3, 1], [6, 1], [3, 1], [0, 1],
                [0, 1], [9, 1], [0, 1], [0, 1], [3, 1],
            ]
        )
    )

    windowed = trailing_mean(aggregate, window_days=3.0)

    # The two leading bins have no complete 3-day window, so 10 bins -> 8.
    assert windowed.counts.shape == (8, 2)
    expected_first_column = [
        3.0,  # bin 2: (0 + 3 + 6) / 3
        4.0,  # bin 3: (3 + 6 + 3) / 3
        3.0,  # bin 4: (6 + 3 + 0) / 3
        1.0,  # bin 5: (3 + 0 + 0) / 3
        3.0,  # bin 6: (0 + 0 + 9) / 3
        3.0,  # bin 7: (0 + 9 + 0) / 3
        3.0,  # bin 8: (9 + 0 + 0) / 3
        1.0,  # bin 9: (0 + 0 + 3) / 3
    ]
    np.testing.assert_allclose(windowed.counts[:, 0], expected_first_column)
    np.testing.assert_allclose(windowed.counts[:, 1], np.ones(8))


def test_result_records_its_coverage_while_the_step_stays_the_bin():
    # `days_per_bin` is the *step* (one frame still advances one day); the new
    # `window_days` is the *coverage*. A single field could not say both.
    aggregate = build_aggregate(np.zeros((10, 2), dtype="int64"))

    windowed = trailing_mean(aggregate, window_days=7.0)

    assert windowed.window_days == 7.0
    assert windowed.days_per_bin == 1.0
    # An unwindowed Aggregate is disjoint: coverage == step, spelled None.
    assert aggregate.window_days is None


def test_a_window_of_one_bin_is_a_no_op():
    # The legal "windowing off" setting: it must not float the counts, drop a
    # bin, or claim a coverage it does not have.
    counts = np.array([[0, 1], [3, 1], [6, 1]], dtype="int64")
    aggregate = build_aggregate(counts)

    windowed = trailing_mean(aggregate, window_days=1.0)

    np.testing.assert_array_equal(windowed.counts, counts)
    assert windowed.counts.dtype == np.int64
    assert windowed.window_days is None
    np.testing.assert_allclose(windowed.bin_starts, aggregate.bin_starts)


def test_a_window_that_is_not_a_whole_number_of_bins_is_rejected():
    # 7 days over 2-day bins is 3.5 bins. Rounding would render an 8-day mean
    # while every label claimed 7, so it is a config error — and the message
    # names the two values that would work.
    aggregate = build_aggregate(np.zeros((10, 2), dtype="int64"), days_per_bin=2.0)

    with pytest.raises(ValueError, match="6.*8"):
        trailing_mean(aggregate, window_days=7.0)


def test_a_window_shorter_than_one_bin_is_rejected():
    # Not roundable to anything meaningful: the bin is already wider than the
    # window asked for.
    aggregate = build_aggregate(np.zeros((10, 2), dtype="int64"), days_per_bin=5.0)

    with pytest.raises(ValueError, match="shorter than"):
        trailing_mean(aggregate, window_days=2.0)


def test_windowing_counts_equals_windowing_the_rates():
    # Population is constant in time, so the window and the per-100k divide
    # commute. This is what licenses windowing *counts* even though the map
    # re-derives a **Cell rate** from separate counts/population grids: if it
    # ever stopped holding, the rate map would be wrong and no other test here
    # would notice.
    counts = np.array([[0, 4], [3, 1], [6, 7], [3, 0], [9, 2], [1, 5]])
    aggregate = build_aggregate(counts)
    population = {0: 1000, 10: 500}

    windowed_counts = trailing_mean(aggregate, window_days=3.0).rate_per_100k(
        population
    )

    rates = aggregate.rate_per_100k(population)
    windowed_rates = np.array(
        [rates[index - 2:index + 1].mean(axis=0) for index in range(2, len(rates))]
    )
    np.testing.assert_allclose(windowed_counts, windowed_rates)


def test_surviving_bins_keep_their_own_start_days():
    # A frame is labelled by its window's END day (the "as of" convention), so
    # the truncated bin_starts must be the tail of the original, not a shifted
    # copy — a whole-window date error would otherwise look plausible.
    aggregate = build_aggregate(np.zeros((10, 2), dtype="int64"), time_start=100.0)

    windowed = trailing_mean(aggregate, window_days=3.0)

    assert windowed.bin_starts[0] == 102.0
    np.testing.assert_allclose(windowed.bin_starts, aggregate.bin_starts[2:])
    assert len(windowed.bin_starts) == len(windowed.counts)


def test_sub_day_bins_window_by_days_not_by_bins():
    # days_per_bin is a float: a 7-day window over half-day bins is 14 bins,
    # so 13 are dropped, not 6.
    aggregate = build_aggregate(np.ones((20, 2), dtype="int64"), days_per_bin=0.5)

    windowed = trailing_mean(aggregate, window_days=7.0)

    assert windowed.counts.shape == (7, 2)
    assert windowed.window_days == 7.0
    assert windowed.days_per_bin == 0.5
    # Every bin held 1, so every 14-bin mean is 1.
    np.testing.assert_allclose(windowed.counts, np.ones((7, 2)))


def test_a_window_longer_than_the_run_is_rejected():
    # Every bin's window would be incomplete, so the drop rule leaves nothing.
    # Caught here rather than downstream, where an empty Aggregate surfaces as
    # an obscure failure while fixing the global colour scale.
    aggregate = build_aggregate(np.ones((5, 2), dtype="int64"))

    with pytest.raises(ValueError, match="longer than"):
        trailing_mean(aggregate, window_days=9.0)
