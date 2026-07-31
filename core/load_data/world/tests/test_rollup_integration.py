"""A **Rollup** end to end: World file -> ancestor map -> rolled `Aggregate`.

Lives on the World side of the seam on purpose. `core/aggregate` must import
nothing from `core/load_data/world` (ADR-0003), and that holds for its tests
too; here the dependency runs the permitted way round.
"""

import numpy as np

from core.aggregate.aggregate import Aggregate
from core.aggregate.rollup import rollup
from core.aggregate.trailing_window import trailing_mean
from core.load_data.world import load_world


def test_a_world_file_rolls_an_aggregate_up_to_its_regions(ragged_world_fixture_path):
    # The whole point of the two halves: an Aggregate keyed on areas becomes one
    # keyed on regions, with North (40 + 50) and South (60) summed per bin.
    world = load_world(ragged_world_fixture_path)
    aggregate = Aggregate(
        counts=np.array([[1, 2, 4], [10, 20, 40]]),
        geo_unit_ids=np.array([40, 50, 60]),
        bin_starts=np.array([0.0, 1.0]),
        days_per_bin=1.0,
        event_type="infections",
    )

    rolled = rollup(aggregate, world.ancestor_by_geo_unit("region"))

    np.testing.assert_array_equal(rolled.geo_unit_ids, [2, 3])
    np.testing.assert_array_equal(rolled.counts, [[3, 4], [30, 40]])


def test_the_ragged_branch_survives_a_region_rollup_and_places_at_nation(
    ragged_world_fixture_path,
):
    # Area 70 hangs straight off the nation: it has no region above it, so a
    # rollup to "region" must keep its own column (counts conserved), while a
    # rollup to "nation" places it like any other. Both orders of level are
    # driven off the same registry, whose order the hierarchy contradicts.
    world = load_world(ragged_world_fixture_path)
    aggregate = Aggregate(
        counts=np.array([[1, 2, 4, 8]]),
        geo_unit_ids=np.array([40, 50, 60, 70]),
        bin_starts=np.array([0.0]),
        days_per_bin=1.0,
        event_type="infections",
    )

    by_region = rollup(aggregate, world.ancestor_by_geo_unit("region"))
    by_nation = rollup(aggregate, world.ancestor_by_geo_unit("nation"))

    np.testing.assert_array_equal(by_region.geo_unit_ids, [2, 3, 70])
    np.testing.assert_array_equal(by_region.counts, [[3, 4, 8]])
    np.testing.assert_array_equal(by_nation.geo_unit_ids, [1])
    np.testing.assert_array_equal(by_nation.counts, [[15]])
    assert by_region.counts.sum() == by_nation.counts.sum() == aggregate.counts.sum()


def test_rates_on_a_rolled_aggregate_use_the_regions_own_population(
    ragged_world_fixture_path,
):
    # The claim that rollup needs no new rate machinery: population is already
    # subtree-aggregated, so a region's denominator is its own entry in the
    # existing map. North has 5 residents (3 + 2), South 4. Dividing by a
    # child's population instead — or summing the children's rates — would
    # inflate North's figure by 2.5x here.
    world = load_world(ragged_world_fixture_path)
    aggregate = Aggregate(
        counts=np.array([[1, 2, 4]]),
        geo_unit_ids=np.array([40, 50, 60]),
        bin_starts=np.array([0.0]),
        days_per_bin=1.0,
        event_type="infections",
    )

    rolled = rollup(aggregate, world.ancestor_by_geo_unit("region"))
    rates = rolled.rate_per_100k(world.population_by_geo_unit())

    # North: 3 events / 5 people; South: 4 / 4.
    np.testing.assert_allclose(rates, [[3 / 5 * 100_000, 4 / 4 * 100_000]])


def test_rolling_up_and_windowing_commute(ragged_world_fixture_path):
    # Both transforms are linear, so the order an animator or notebook applies
    # them in cannot change a number. Without this, a config that windowed
    # before rolling could differ from one that rolled first and nobody would
    # know which was right.
    world = load_world(ragged_world_fixture_path)
    counts = np.array([[0, 4, 1], [3, 1, 2], [6, 7, 0], [3, 0, 5], [9, 2, 4]])
    aggregate = Aggregate(
        counts=counts,
        geo_unit_ids=np.array([40, 50, 60]),
        bin_starts=np.arange(5, dtype="float64"),
        days_per_bin=1.0,
        event_type="infections",
    )
    ancestors = world.ancestor_by_geo_unit("region")

    rolled_then_windowed = trailing_mean(rollup(aggregate, ancestors), window_days=3.0)
    windowed_then_rolled = rollup(trailing_mean(aggregate, window_days=3.0), ancestors)

    np.testing.assert_allclose(
        rolled_then_windowed.counts, windowed_then_rolled.counts
    )
    np.testing.assert_array_equal(
        rolled_then_windowed.geo_unit_ids, windowed_then_rolled.geo_unit_ids
    )
    np.testing.assert_allclose(
        rolled_then_windowed.bin_starts, windowed_then_rolled.bin_starts
    )
    assert rolled_then_windowed.window_days == windowed_then_rolled.window_days == 3.0
