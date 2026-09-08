"""Rasterise geo-unit centroids into a density-heatmap grid (ADR-0007).

Each **Frame** is drawn as a smoothed grid, not discrete marks. Centroids —
already projected to UTM metres (:mod:`projection`) — are binned into a grid over
the UTM bounding box; per-unit *counts* and *population* are accumulated into
*separate* grids so a cell's rate is re-derived as
``cell_counts / cell_population * 1e5``. Summing per-unit rates instead would let
dense metro cells read hot purely from centroid crowding — the mistake this
module exists to avoid.

Pure numpy (borrowed maths from ``june_animator/src/map_utils.py``); smoothing
(:func:`smooth_grid`) lazy-imports scipy, so the module stays render-free
(ADR-0002).
"""

from __future__ import annotations

import numpy as np


def utm_grid_geometry(
    utm_bbox: dict[str, float],
    figure_height: float,
    grid_resolution: float,
) -> tuple[tuple[float, float], tuple[int, int]]:
    """``(figsize, grid_shape)`` for a UTM (metric) map.

    UTM is conformal, so cells are square in metres and no meridian-convergence
    correction is needed. ``grid_resolution`` is cells per km. Borrowed from
    ``map_utils.utm_figure_geometry``.
    """
    easting_span = utm_bbox["east"] - utm_bbox["west"]
    northing_span = utm_bbox["north"] - utm_bbox["south"]

    figure_width = figure_height * easting_span / northing_span
    figsize = (figure_width, figure_height)

    cell_size_m = 1000.0 / grid_resolution
    n_rows = max(1, round(northing_span / cell_size_m))
    n_cols = max(1, round(easting_span / cell_size_m))
    return figsize, (n_rows, n_cols)


def compute_cell_indices(
    eastings: np.ndarray,
    northings: np.ndarray,
    utm_bbox: dict[str, float],
    grid_shape: tuple[int, int],
) -> np.ndarray:
    """Flat cell index per centroid; out-of-box centroids get ``-1``.

    Row 0 is the north edge (northing decreases with row), matching image
    orientation. Borrowed from ``map_utils.compute_grid_indices``, working in UTM
    metres rather than degrees.
    """
    height, width = grid_shape
    easting_span = utm_bbox["east"] - utm_bbox["west"]
    northing_span = utm_bbox["north"] - utm_bbox["south"]

    row = np.floor(
        (utm_bbox["north"] - northings) / northing_span * height
    ).astype(np.int64)
    col = np.floor(
        (eastings - utm_bbox["west"]) / easting_span * width
    ).astype(np.int64)
    valid = (row >= 0) & (row < height) & (col >= 0) & (col < width)
    return np.where(valid, row * width + col, -1).astype(np.int64)


def accumulate_to_grid(
    flat_indices: np.ndarray,
    values: np.ndarray,
    grid_shape: tuple[int, int],
) -> np.ndarray:
    """Sum ``values`` into their cells; ``-1`` (out-of-box) entries are skipped.

    Borrowed from ``map_utils.rasterize_to_grid``.
    """
    height, width = grid_shape
    keep = flat_indices >= 0
    grid = np.bincount(
        flat_indices[keep],
        weights=values[keep].astype(np.float64),
        minlength=height * width,
    )
    return grid.reshape(height, width)


def cell_rate_grid(
    counts_grid: np.ndarray,
    population_grid: np.ndarray,
) -> np.ndarray:
    """Re-derived areal rate per cell: ``counts / population * 1e5``.

    A cell with no population yields NaN (undefined rate, not inf/0), so the
    alpha ramp leaves it transparent and it is excluded from the global scale.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        rate = counts_grid / population_grid * 100_000.0
    rate[population_grid == 0] = np.nan
    return rate


def metric_grids(
    eastings: np.ndarray,
    northings: np.ndarray,
    counts: np.ndarray,
    population: np.ndarray,
    utm_bbox: dict[str, float],
    grid_shape: tuple[int, int],
    *,
    metric: str = "rate_per_100k",
) -> list[np.ndarray]:
    """One cell grid per bin for ``metric`` ('rate_per_100k' or 'count').

    ``counts`` is the dense ``(n_bins, n_units)`` matrix; ``population`` and the
    centroid arrays are per-unit and *fixed across bins*. The bin-invariant work —
    cell indexing and the denominator grid (population for rate, occupancy for
    count) — is done once, and only the per-bin counts accumulation varies. Grids
    are raw (unsmoothed), aligned to ``counts`` rows.

    For rate, counts and population are accumulated separately then divided
    (density-independent). For count, empty cells are NaN so they render
    transparent like the rate path (rather than a solid floor of zeros).
    """
    flat = compute_cell_indices(eastings, northings, utm_bbox, grid_shape)

    if metric == "count":
        occupied = accumulate_to_grid(
            flat, np.ones(flat.shape[0], dtype="float64"), grid_shape
        )
        grids = []
        for counts_row in counts:
            grid = accumulate_to_grid(flat, counts_row, grid_shape)
            grid[occupied == 0] = np.nan
            grids.append(grid)
        return grids

    if metric == "rate_per_100k":
        population_grid = accumulate_to_grid(flat, population, grid_shape)
        return [
            cell_rate_grid(
                accumulate_to_grid(flat, counts_row, grid_shape), population_grid
            )
            for counts_row in counts
        ]

    raise ValueError(
        f"Unknown metric {metric!r}; expected 'rate_per_100k' or 'count'."
    )


def smooth_grid(grid: np.ndarray, sigma: float) -> np.ndarray:
    """Isotropic Gaussian smoothing (grid-cell units). Lazy-imports scipy.

    NaNs are treated as absence: smoothing runs on a zero-filled copy so empty
    cells do not poison their neighbours, and originally-NaN cells stay NaN.
    Borrowed from ``map_utils.smooth_grid``.
    """
    from scipy.ndimage import gaussian_filter

    empty = np.isnan(grid)
    filled = np.where(empty, 0.0, grid)
    smoothed = gaussian_filter(filled, sigma=sigma)
    smoothed[empty] = np.nan
    return smoothed
