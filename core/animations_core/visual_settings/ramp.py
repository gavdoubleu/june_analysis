"""Colour ramp + global normalisation for the density heatmap.

Two cosmetic concerns, both config-driven (``RenderConfig.ramp`` / ``alpha_power``):

- **Global scale** — the colour scale is fixed across every frame (ADR-0006), so
  ``vmin/vmax`` are computed once over all per-frame cell grids, NaN-aware (empty
  cells are NaN and excluded). Floored at zero: the ramp encodes magnitude.
- **Alpha ramp** — a perceptually-uniform sequential ramp (default ``inferno``)
  whose alpha rises from 0, so low/empty cells fade to transparent and the
  basemap shows through.

Matplotlib is lazy-imported inside :func:`build_alpha_ramp` (ADR-0002);
:func:`global_value_range` is pure numpy.
"""

from __future__ import annotations

import numpy as np


def global_value_range(grids) -> tuple[float, float]:
    """``(vmin, vmax)`` over every frame's cell grid, NaN-aware.

    ``vmin`` is 0 (magnitude ramp); ``vmax`` the global max across all grids. An
    all-empty stack (every cell NaN) returns a non-degenerate ``(0, 1)`` so
    ``matplotlib.colors.Normalize`` does not divide by zero.
    """
    stacked = np.stack([np.asarray(grid, dtype="float64") for grid in grids])
    if np.all(np.isnan(stacked)):
        return 0.0, 1.0
    vmax = float(np.nanmax(stacked))
    if vmax <= 0.0:
        return 0.0, 1.0
    return 0.0, vmax


def build_alpha_ramp(ramp_name: str = "inferno", alpha_power: float = 1.0):
    """A ``ListedColormap`` of ``ramp_name`` whose alpha ramps 0 -> 1.

    ``alpha_power`` shapes the fade: ``1`` linear, ``<1`` faster onset (low values
    more visible), ``>1`` opaque only near the max. Borrowed from
    ``map_utils.build_alpha_colormap``; lazy-imports matplotlib.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    base = plt.get_cmap(ramp_name)
    colours = base(np.linspace(0, 1, 256))
    colours[:, 3] = np.linspace(0, 1, 256) ** alpha_power
    return ListedColormap(colours)
