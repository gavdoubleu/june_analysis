"""Tracer 2-3: raster maths for the density heatmap.

Centroids (projected to UTM metres) are binned into a grid; counts and
population are accumulated *separately* so a grid cell's rate is re-derived as
``cell_counts / cell_population * 1e5`` (the resolved 'cell reduce' decision) —
never a sum of per-unit rates, which would let centroid crowding read as heat.

Pure numpy, no render deps.
"""

import numpy as np

from core.animations_core.build_animation.raster import (
    accumulate_to_grid,
    cell_rate_grid,
    compute_cell_indices,
    metric_grids,
)

# A 2x2 grid over a 0..100 x 0..100 UTM box; two east/north points that fall in
# the same cell, plus one outside the box.
UTM_BBOX = {"west": 0.0, "east": 100.0, "south": 0.0, "north": 100.0}
GRID_SHAPE = (2, 2)


def test_nearby_centroids_share_a_cell_outsider_is_dropped():
    eastings = np.array([25.0, 30.0, 200.0])
    northings = np.array([25.0, 30.0, 25.0])
    flat = compute_cell_indices(eastings, northings, UTM_BBOX, GRID_SHAPE)
    # (25,25) and (30,30) -> row 1, col 0 -> flat 2; (200,25) is out of bounds.
    assert flat.tolist() == [2, 2, -1]


def test_accumulate_sums_values_per_cell_skipping_negatives():
    flat = np.array([2, 2, -1])
    values = np.array([5.0, 3.0, 99.0])
    grid = accumulate_to_grid(flat, values, GRID_SHAPE)
    assert grid.shape == GRID_SHAPE
    assert grid[1, 0] == 8.0  # 5 + 3
    assert grid.sum() == 8.0  # the -1 (out-of-bounds) value is discarded


def test_cell_rate_is_counts_over_population_zero_pop_is_nan():
    counts_grid = np.array([[0.0, 0.0], [8.0, 0.0]])
    population_grid = np.array([[0.0, 0.0], [3000.0, 0.0]])
    rate = cell_rate_grid(counts_grid, population_grid)
    assert np.isclose(rate[1, 0], 8.0 / 3000.0 * 1e5)
    # cells with no population -> NaN (transparent), not inf or 0.
    assert np.isnan(rate[0, 0])
    assert np.isnan(rate[1, 1])


def test_metric_grids_rate_re_derives_from_crowded_cell():
    # Two units in one cell: counts [5, 3], pop [1000, 2000]. The cell rate must
    # be (5+3)/(1000+2000)*1e5, NOT rate1+rate2 (which crowding would inflate).
    eastings = np.array([25.0, 30.0])
    northings = np.array([25.0, 30.0])
    counts = np.array([[5.0, 3.0]])  # one bin
    population = np.array([1000.0, 2000.0])
    grids = metric_grids(
        eastings, northings, counts, population, UTM_BBOX, GRID_SHAPE,
        metric="rate_per_100k",
    )
    assert np.isclose(grids[0][1, 0], 8.0 / 3000.0 * 1e5)


def test_metric_grids_count_sums_counts_empty_is_nan():
    eastings = np.array([25.0, 30.0])
    northings = np.array([25.0, 30.0])
    counts = np.array([[5.0, 3.0]])  # one bin
    population = np.array([1000.0, 2000.0])
    grids = metric_grids(
        eastings, northings, counts, population, UTM_BBOX, GRID_SHAPE,
        metric="count",
    )
    assert grids[0][1, 0] == 8.0
    # empty cells carry no events -> NaN so the alpha ramp leaves them transparent.
    assert np.isnan(grids[0][0, 0])


def test_metric_grids_shares_invariants_across_bins():
    # Two bins, same geometry/population: each bin reads strictly its own counts,
    # and the shared denominator is applied identically.
    eastings = np.array([25.0, 30.0])
    northings = np.array([25.0, 30.0])
    counts = np.array([[5.0, 3.0], [1.0, 1.0]])  # two bins
    population = np.array([1000.0, 2000.0])
    grids = metric_grids(
        eastings, northings, counts, population, UTM_BBOX, GRID_SHAPE,
        metric="rate_per_100k",
    )
    assert len(grids) == 2
    assert np.isclose(grids[0][1, 0], 8.0 / 3000.0 * 1e5)
    assert np.isclose(grids[1][1, 0], 2.0 / 3000.0 * 1e5)
