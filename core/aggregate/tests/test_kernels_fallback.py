"""numba is an optional JIT speed-up: the pure-numpy fallback must give
identical results, and `core.aggregate` must import with numba uninstalled."""

import numpy as np
import pytest

from ..aggregate import aggregate_events
from ..kernels import count_dense, numba_available


@pytest.fixture
def larger_events():
    rng = np.random.default_rng(0)
    n = 5000
    return {
        "time": rng.uniform(0.0, 30.0, n),
        "venue_geo_unit_id": rng.integers(0, 50, n),
    }


def test_numpy_and_numba_paths_give_identical_dense_counts():
    rng = np.random.default_rng(1)
    n_bins, n_geo = 30, 50
    bin_indices = rng.integers(0, n_bins, 5000)
    geo_indices = rng.integers(0, n_geo, 5000)

    numpy_counts = count_dense(bin_indices, geo_indices, n_bins, n_geo, use_numba=False)
    auto_counts = count_dense(bin_indices, geo_indices, n_bins, n_geo, use_numba=None)

    np.testing.assert_array_equal(numpy_counts, auto_counts)
    assert numpy_counts.sum() == 5000


def test_aggregate_events_identical_across_kernels(larger_events):
    import pandas as pd

    events = pd.DataFrame(larger_events)
    numpy_aggregate = aggregate_events(
        events, event_type="infections", days_per_bin=1.0, use_numba=False
    )
    numba_aggregate = aggregate_events(
        events, event_type="infections", days_per_bin=1.0, use_numba=None
    )
    np.testing.assert_array_equal(numpy_aggregate.counts, numba_aggregate.counts)


def test_numba_flag_reports_environment():
    # Documents the current environment; parity holds regardless of its value.
    assert isinstance(numba_available(), bool)
