"""Behaviour of ``World.ancestor_by_geo_unit`` — the hierarchy half of a **Rollup**.

Exercises the public surface only, over the ragged three-level fixture (see
``fixtures/build_ragged_fixture.py`` for the tree and why it is shaped that way).
"""

import h5py
import numpy as np
import pytest

from core.load_data.world import load_world


def test_units_map_to_their_parent_at_the_requested_level(ragged_world_fixture_path):
    # The core walk: each area resolves to the region above it. Mapping an area
    # to its own id, or to the nation, would key a rolled Aggregate wrongly.
    world = load_world(ragged_world_fixture_path)

    ancestors = world.ancestor_by_geo_unit("region")

    assert ancestors[40] == 2
    assert ancestors[50] == 2
    assert ancestors[60] == 3


def test_the_walk_climbs_more_than_one_level(ragged_world_fixture_path):
    # Area -> nation is two hops. A single-step "use the parent" implementation
    # would answer 2 (a region) here and pass the one-hop test above.
    world = load_world(ragged_world_fixture_path)

    ancestors = world.ancestor_by_geo_unit("nation")

    assert ancestors[40] == 1
    assert ancestors[60] == 1


def test_a_unit_already_at_the_requested_level_maps_to_itself(
    ragged_world_fixture_path,
):
    # Rolling an Aggregate to the level it already keys on must be an identity.
    # Starting the walk at `unit.parent` would send each region to the nation
    # and silently produce national totals under region labels.
    world = load_world(ragged_world_fixture_path)

    ancestors = world.ancestor_by_geo_unit("region")

    assert ancestors[2] == 2
    assert ancestors[3] == 3


def test_units_with_no_ancestor_at_the_level_are_omitted(ragged_world_fixture_path):
    # Area 70 hangs straight off the nation and the nation is coarser than a
    # region: neither has a region ancestor. Inventing one (or mapping them to
    # a shared bucket) would merge unrelated counts; the omission is what lets
    # `rollup` keep their own columns and warn once.
    world = load_world(ragged_world_fixture_path)

    ancestors = world.ancestor_by_geo_unit("region")

    assert 70 not in ancestors
    assert 1 not in ancestors


def test_the_returned_map_is_the_callers_to_mutate(ragged_world_fixture_path):
    # Handed across the seam into `rollup`, so it must not be the World's own
    # state: a caller editing it would corrupt every later rollup.
    world = load_world(ragged_world_fixture_path)

    world.ancestor_by_geo_unit("region")[40] = 999

    assert world.ancestor_by_geo_unit("region")[40] == 2


def test_an_unknown_level_name_raises_listing_the_runs_own_levels(
    ragged_world_fixture_path,
):
    # Level names are per-run, so a typo (or a name from another run) would
    # otherwise return an empty map and silently roll every column up to
    # nothing. The message has to name what this run actually offers.
    world = load_world(ragged_world_fixture_path)

    with pytest.raises(ValueError, match="borough"):
        world.ancestor_by_geo_unit("borough")


def test_the_levels_offered_are_listed_coarse_to_fine(ragged_world_fixture_path):
    # From `metadata/registries/geo_levels`, never `GeographyManager.levels`,
    # which is first-seen over unit file order — here ["area", "region",
    # "nation"]. The order is the information: it tells the reader which way is
    # coarser, so a sorted or first-seen list would misinform.
    world = load_world(ragged_world_fixture_path)

    with pytest.raises(ValueError, match="'nation', 'region', 'area'"):
        world.ancestor_by_geo_unit("borough")


def test_the_hierarchys_own_level_order_is_wrong_and_nothing_relies_on_it(
    ragged_world_fixture_path,
):
    # The upstream trap, pinned executably. `metadata/registries/geo_levels` is
    # written coarse->fine, but `load_geography` recomputes
    # `GeographyManager.levels` as first-seen over unit *file* order, which is
    # sorted by unit id and has no relation to depth. This fixture lists areas
    # first, so the two disagree — the registry is the only ordered source.
    #
    # If this assertion ever starts failing because the orders agree, the
    # fixture has stopped exercising the trap (or upstream fixed it); check
    # which before deleting the test.
    world = load_world(ragged_world_fixture_path)

    assert list(world.geography.levels) == ["area", "region", "nation"]
    assert world.geo_levels() == ["nation", "region", "area"]

    # And resolution is unaffected, because the parent walk compares level
    # *names* and never asks which of two levels is coarser.
    assert world.ancestor_by_geo_unit("region")[40] == 2
    assert world.ancestor_by_geo_unit("nation")[40] == 1


def test_a_world_file_with_no_level_registry_still_rolls_up(tmp_path):
    # Not every World file carries `metadata/registries/geo_levels`; there,
    # levels are stored as names on each unit. The parent walk never needed the
    # ordering, so only the "coarsest first" claim degrades — refusing to
    # validate at all, or requiring the registry, would break such runs.
    path = _build_registryless_world(tmp_path / "world_state_no_registry.h5")
    world = load_world(path)

    assert sorted(world.geo_levels()) == ["area", "region"]
    assert world.ancestor_by_geo_unit("region") == {10: 10, 20: 10, 30: 10}


def _build_registryless_world(path):
    """A two-level World file storing level *names*, with no level registry."""
    string_dtype = h5py.string_dtype(encoding="utf-8")
    names = np.array(["North", "A", "B"], dtype=object)
    levels = np.array(["region", "area", "area"], dtype=object)

    with h5py.File(path, "w") as world_file:
        geography = world_file.create_group("geography")
        geography.create_dataset("ids", data=np.array([10, 20, 30], dtype=np.int64))
        geography.create_dataset("names", data=names.astype("S"), dtype=string_dtype)
        geography.create_dataset("levels", data=levels.astype("S"), dtype=string_dtype)
        geography.create_dataset(
            "parent_ids", data=np.array([-1, 10, 10], dtype=np.int64)
        )

        population = world_file.create_group("population")
        population.create_dataset("ids", data=np.arange(2, dtype=np.int64))
        population.create_dataset(
            "geo_unit_ids", data=np.array([20, 30], dtype=np.int64)
        )
        population.create_dataset("ages", data=np.array([30, 40], dtype=np.int64))
        population.create_dataset("sexes", data=np.array([0, 1], dtype=np.int64))

    return path
