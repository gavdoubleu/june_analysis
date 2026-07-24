"""Behaviour tests for ``Aggregate.rate_per_100k`` (population normalisation).

Population is passed *in* as a ``{geo_unit_id: population}`` map — the aggregate
never imports ``core/load_data/world`` (ADR-0003).
"""

import numpy as np
import pytest

from ..aggregate import aggregate_events


def test_rate_per_100k_matches_population(enriched_events_simple):
    aggregate = aggregate_events(enriched_events_simple, event_type="infection")
    # geo_unit_ids == [10, 20]; counts == [[2, 1], [1, 2]].
    rate = aggregate.rate_per_100k({10: 1000, 20: 2000})

    # counts / population * 100_000, column-aligned to geo_unit_ids.
    expected = np.array([[200.0, 50.0], [100.0, 100.0]])
    np.testing.assert_allclose(rate, expected)


def test_geo_unit_missing_from_population_yields_nan_column_and_warns(
    enriched_events_simple, caplog
):
    aggregate = aggregate_events(enriched_events_simple, event_type="infection")

    with caplog.at_level("WARNING"):
        rate = aggregate.rate_per_100k({10: 1000})  # geo 20 absent

    # Known unit still computed; the absent one is all-NaN, not a crash.
    np.testing.assert_allclose(rate[:, 0], [200.0, 100.0])
    assert np.isnan(rate[:, 1]).all()
    assert "20" in caplog.text and "population" in caplog.text


def test_zero_population_yields_nan_not_inf(enriched_events_simple):
    aggregate = aggregate_events(enriched_events_simple, event_type="infection")

    rate = aggregate.rate_per_100k({10: 0, 20: 2000})

    assert np.isnan(rate[:, 0]).all()  # not inf
    np.testing.assert_allclose(rate[:, 1], [50.0, 100.0])
