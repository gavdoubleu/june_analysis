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
from datetime import date, datetime, time, timedelta

import numpy as np

from ..config import RenderConfig
from ..visual_settings.ramp import global_value_range
from .projection import utm_epsg, wgs84_to_utm
from .raster import metric_grid, smooth_grid, utm_grid_geometry

_METRIC_LABELS = {"rate_per_100k": "rate per 100k", "count": "count"}

# Pad the auto-detected UTM bbox by this fraction of each span so the
# southern/eastern-most units sit strictly inside the grid (see _bounding_box).
_BBOX_MARGIN = 0.03


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
    if config.metric == "rate_per_100k":
        _require_populations(aggregate, population_vector)

    epsg = utm_epsg(
        {int(uid): coordinates[int(uid)] for uid in aggregate.geo_unit_ids}
    )
    eastings, northings = wgs84_to_utm(latitudes, longitudes, epsg)
    utm_bbox = _bounding_box(eastings, northings)

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


def _bounding_box(eastings: np.ndarray, northings: np.ndarray) -> dict[str, float]:
    """UTM bbox around the centroids, padded by ``_BBOX_MARGIN`` of each span.

    Raw min/max place the southern/eastern-most units exactly on the boundary,
    where ``compute_cell_indices`` floors them to ``row==height``/``col==width``
    and discards them. Padding pulls every unit strictly inside the grid.
    """
    east_min, east_max = float(eastings.min()), float(eastings.max())
    north_min, north_max = float(northings.min()), float(northings.max())
    east_pad = (east_max - east_min) * _BBOX_MARGIN
    north_pad = (north_max - north_min) * _BBOX_MARGIN
    return {
        "west": east_min - east_pad,
        "east": east_max + east_pad,
        "south": north_min - north_pad,
        "north": north_max + north_pad,
    }


def _require_populations(aggregate, population_vector: np.ndarray) -> None:
    """Hard-error when a unit carrying events has no population (rate metric).

    ``rate_per_100k`` divides counts by population, so a missing or zero
    population yields NaN, which renders transparent — silently dropping located
    events, the very failure the coordinate policy forbids. Error rather than drop.
    """
    has_events = aggregate.counts.sum(axis=0) > 0
    unpopulated = has_events & (population_vector <= 0)
    if unpopulated.any():
        bad = [int(aggregate.geo_unit_ids[i]) for i in np.flatnonzero(unpopulated)]
        raise ValueError(
            f"{len(bad)} geo unit(s) carry events but have no population: {bad}. "
            "A rate_per_100k map would silently drop their events; supply their "
            "population in the World file or render with metric='count'."
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
    """Per-frame labels: real dates when ``start_date`` set, else day index.

    ``bin_start`` may be fractional (sub-day ``days_per_bin``); labels keep the
    fraction so distinct bins never collapse to the same string. Whole-day bins
    still render as a bare ISO date / integer day.
    """
    if start_date is not None:
        base = datetime(start_date.year, start_date.month, start_date.day)
        return [
            _datetime_label(base + timedelta(days=float(bin_start)))
            for bin_start in bin_starts
        ]
    return [f"Day {bin_start:g}" for bin_start in bin_starts]


def _datetime_label(moment: datetime) -> str:
    """Bare ISO date for a midnight moment, full ISO datetime when sub-day."""
    if moment.time() == time():
        return moment.date().isoformat()
    return moment.isoformat()
