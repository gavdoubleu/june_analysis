"""Data entry point: ``prepare()`` returns render-free :class:`Prepared` (ADR-0007).

``prepare(aggregate, world, config)`` does all the heavy, format-independent work
once — coordinate resolution, UTM projection, per-bin cell grids, smoothing and
the global colour scale — and returns an immutable :class:`Prepared`. The
expensive pipeline runs a single time; the same ``Prepared`` can drive several
:class:`~.scene.Scene`s (different cosmetics) without re-running ``prepare()``.

Frame == Aggregate bin (CONTEXT glossary): one smoothed grid per row of
``aggregate.counts``, each read from strictly its own bin (no temporal
smoothing). The colour scale is global across all frames (ADR-0006).

Coordinate policy: units carrying events *must* map to a coordinate. Missing
coordinates are first back-filled from the World (``infer_missing_coordinates``);
any still-missing unit is a hard error — a map silently dropping located events
would misrepresent the epidemic. (This deliberately diverges from the geo-source
"skip Absent/Malformed" policy; see ADR-0007.)

``prepare()`` is pure data (numpy / pyproj / scipy); matplotlib + cartopy enter
only in :class:`~.scene.Scene` (ADR-0002).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from ..config import RenderConfig
from ..visual_settings.ramp import global_value_range
from .projection import utm_epsg, wgs84_to_utm
from .raster import metric_grid, smooth_grid, utm_grid_geometry

_METRIC_LABELS = {"rate_per_100k": "rate per 100k", "count": "count"}


@dataclass(frozen=True)
class Prepared:
    """Render-ready result of :func:`prepare`: one grid per frame + geometry.

    Pure render-free data (ADR-0002): the grids, the global colour scale and the
    UTM geometry a :class:`~.scene.Scene` needs to draw. Holds no ``config`` and
    owns no matplotlib — ``metric_label`` is the one derived descriptor baked in,
    same category as ``vmin``/``vmax``.
    """

    smoothed_grids: list[np.ndarray]
    frame_labels: list[str]
    utm_bbox: dict[str, float]
    epsg: int
    figsize: tuple[float, float]
    grid_shape: tuple[int, int]
    vmin: float
    vmax: float
    metric_label: str


def prepare(aggregate, world, config: RenderConfig) -> Prepared:
    """Build a :class:`Prepared` from a dense Aggregate + World + RenderConfig.

    Resolves coordinates (inferring then hard-erroring on gaps), projects to UTM,
    rasterises + smooths one grid per bin, and fixes the global colour scale.
    """
    coordinates = _resolve_coordinates(aggregate, world)
    populations = world.population_by_geo_unit()

    latitudes = np.array(
        [coordinates[int(uid)][0] for uid in aggregate.geo_unit_ids]
    )
    longitudes = np.array(
        [coordinates[int(uid)][1] for uid in aggregate.geo_unit_ids]
    )
    population_vector = np.array(
        [populations.get(int(uid), 0) for uid in aggregate.geo_unit_ids],
        dtype="float64",
    )

    epsg = utm_epsg(
        {int(uid): coordinates[int(uid)] for uid in aggregate.geo_unit_ids}
    )
    eastings, northings = wgs84_to_utm(latitudes, longitudes, epsg)
    utm_bbox = {
        "west": float(eastings.min()),
        "east": float(eastings.max()),
        "south": float(northings.min()),
        "north": float(northings.max()),
    }

    figsize, grid_shape = utm_grid_geometry(
        utm_bbox, config.figure_height, config.grid_resolution
    )

    smoothed_grids = [
        smooth_grid(
            metric_grid(
                eastings,
                northings,
                aggregate.counts[bin_index],
                population_vector,
                utm_bbox,
                grid_shape,
                metric=config.metric,
            ),
            config.sigma,
        )
        for bin_index in range(aggregate.counts.shape[0])
    ]

    vmin, vmax = global_value_range(smoothed_grids)
    frame_labels = _frame_labels(aggregate.bin_starts, config.start_date)
    metric_label = _METRIC_LABELS.get(config.metric, config.metric)

    return Prepared(
        smoothed_grids=smoothed_grids,
        frame_labels=frame_labels,
        utm_bbox=utm_bbox,
        epsg=epsg,
        figsize=figsize,
        grid_shape=grid_shape,
        vmin=vmin,
        vmax=vmax,
        metric_label=metric_label,
    )


def _resolve_coordinates(aggregate, world) -> dict[int, tuple[float, float]]:
    """Coordinates for every unit in the aggregate; infer, then hard-error.

    Missing coordinates are back-filled once from the World; any unit still
    uncoordinated raises ``ValueError`` — the map must not drop located events.
    """
    coordinates = world.geo_unit_coords()
    if _missing_units(aggregate.geo_unit_ids, coordinates):
        world.infer_missing_coordinates()
        coordinates = world.geo_unit_coords()

    missing = _missing_units(aggregate.geo_unit_ids, coordinates)
    if missing:
        raise ValueError(
            f"{len(missing)} geo unit(s) carry events but have no coordinate "
            f"even after inference: {missing}. A map cannot place these events; "
            "supply their coordinates in the World file or exclude them upstream."
        )
    return coordinates


def _missing_units(geo_unit_ids, coordinates) -> list[int]:
    """Units in ``geo_unit_ids`` absent from the coordinate map."""
    return [int(uid) for uid in geo_unit_ids if int(uid) not in coordinates]


def _frame_labels(bin_starts, start_date: date | None) -> list[str]:
    """Per-frame labels: real ISO dates when ``start_date`` set, else day index."""
    if start_date is not None:
        return [
            (start_date + timedelta(days=int(bin_start))).isoformat()
            for bin_start in bin_starts
        ]
    return [f"Day {int(bin_start)}" for bin_start in bin_starts]
