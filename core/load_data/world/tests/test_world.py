"""Behaviour tests for the ``core/load_data/world`` wrapper.

Exercises the public surface only: ``load_world`` and the ``World`` accessors.
"""

import pytest

from core.load_data.world import load_world


def test_geo_unit_coords_returns_lat_lon_for_units_with_coordinates(world_fixture_path):
    world = load_world(world_fixture_path)

    # Region 10 has no stored coordinates; only the two areas do (lat, lon WGS84).
    assert world.geo_unit_coords() == {20: (51.0, -1.0), 30: (53.0, -3.0)}


def test_infer_missing_coordinates_fills_parent_from_children_mean(world_fixture_path):
    world = load_world(world_fixture_path)

    inferred_count = world.infer_missing_coordinates()

    # Region 10 gains the mean of areas 20 and 30: ((51+53)/2, (-1+-3)/2).
    assert inferred_count == 1
    assert world.geo_unit_coords()[10] == (52.0, -2.0)


def test_population_by_geo_unit_is_subtree_aggregated(world_fixture_path):
    world = load_world(world_fixture_path)

    # Areas hold their direct residents; the region sums its subtree (3 + 2).
    assert world.population_by_geo_unit() == {20: 3, 30: 2, 10: 5}


def test_missing_world_file_raises_clear_error(tmp_path):
    missing = tmp_path / "does_not_exist.h5"

    with pytest.raises(FileNotFoundError, match="World file"):
        load_world(missing)
