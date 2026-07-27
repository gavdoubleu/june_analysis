"""Two-step render entry point: ``prepare()`` then ``Prepared.write()`` (ADR-0007).

``prepare(aggregate, world, config)`` does all the heavy, format-independent work
once — coordinate resolution, UTM projection, per-bin cell grids, smoothing and
the global colour scale — and returns an immutable :class:`Prepared`. The
expensive pipeline runs a single time; the same ``Prepared`` can then be written
to several formats.

Frame == Aggregate bin (CONTEXT glossary): one smoothed grid per row of
``aggregate.counts``, each read from strictly its own bin (no temporal
smoothing). The colour scale is global across all frames (ADR-0006).

Coordinate policy: units carrying events *must* map to a coordinate. Missing
coordinates are first back-filled from the World (``infer_missing_coordinates``);
any still-missing unit is a hard error — a map silently dropping located events
would misrepresent the epidemic. (This deliberately diverges from the geo-source
"skip Absent/Malformed" policy; see ADR-0007.)

``prepare()`` is pure data (numpy / pyproj / scipy); matplotlib + cartopy enter
only in :meth:`Prepared.build_layout` / :meth:`Prepared.draw_frame` (ADR-0002).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

from ..visual_settings.ramp import global_value_range
from . import layout as layout_module
from .projection import utm_epsg, wgs84_to_utm
from .raster import metric_grid, smooth_grid, utm_grid_geometry

_METRIC_LABELS = {"rate_per_100k": "rate per 100k", "count": "count"}


@dataclass(frozen=True)
class Prepared:
    """Render-ready result of :func:`prepare`: one grid per frame + geometry.

    Holds everything both the layout and the frame loop need; drawing is
    deferred so the same ``Prepared`` can be written to multiple formats.
    """

    smoothed_grids: list[np.ndarray]
    frame_labels: list[str]
    utm_bbox: dict[str, float]
    epsg: int
    figsize: tuple[float, float]
    grid_shape: tuple[int, int]
    vmin: float
    vmax: float
    config: Any

    def build_layout(self):
        """Build the static scene (map + basemap + colourbar) for this render.

        Returns ``(Layout, ScalarMappable)``; the mappable carries the global
        norm + cmap that :meth:`draw_frame` reuses so frames match the bar.
        """
        from ..visual_settings.ramp import build_alpha_ramp

        cmap = build_alpha_ramp(self.config.ramp, self.config.alpha_power)
        scene = layout_module.create_layout(
            self.figsize,
            self.config.dpi,
            self.utm_bbox,
            self.epsg,
            title=self.config.title,
        )
        basemap_array = self._load_basemap()
        layout_module.draw_basemap(
            scene.map_axis, basemap_array, self.utm_bbox, scene.data_crs
        )
        label = _METRIC_LABELS.get(self.config.metric, self.config.metric)
        mappable = layout_module.add_colourbar(
            scene.figure,
            scene.colourbar_axis,
            cmap,
            self.vmin,
            self.vmax,
            label=label,
        )
        return scene, mappable

    def draw_frame(self, scene, mappable, index: int) -> None:
        """Draw frame ``index``: update the heatmap layer and the date ticker.

        The heatmap ``AxesImage`` is created on the first call and reused (its
        data swapped) thereafter, so an animation writer updates one artist.
        """
        grid = self.smoothed_grids[index]
        extent = (
            self.utm_bbox["west"],
            self.utm_bbox["east"],
            self.utm_bbox["south"],
            self.utm_bbox["north"],
        )
        if scene.heatmap_image is None:
            scene.heatmap_image = scene.map_axis.imshow(
                grid,
                extent=extent,
                origin="upper",
                transform=scene.data_crs,
                cmap=mappable.cmap,
                norm=mappable.norm,
                zorder=1,
            )
        else:
            scene.heatmap_image.set_data(grid)
        scene.date_text.set_text(self.frame_labels[index])

    def _load_basemap(self):
        """Custom ``background_image`` if set, else the fetched/cached ESRI tile."""
        from . import basemap as basemap_module

        if self.config.background_image is not None:
            import numpy as _np
            from PIL import Image

            return _np.asarray(
                Image.open(self.config.background_image).convert("RGB")
            )
        return basemap_module.load_basemap(
            self.utm_bbox,
            self.epsg,
            self.figsize,
            self.config.dpi,
            cache_dir=self.config.cache_dir,
            require_basemap=self.config.require_basemap,
        )


def prepare(aggregate, world, config) -> Prepared:
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

    return Prepared(
        smoothed_grids=smoothed_grids,
        frame_labels=frame_labels,
        utm_bbox=utm_bbox,
        epsg=epsg,
        figsize=figsize,
        grid_shape=grid_shape,
        vmin=vmin,
        vmax=vmax,
        config=config,
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
