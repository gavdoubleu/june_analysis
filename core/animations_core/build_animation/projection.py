"""Geographic projection maths for the animator: UTM zone/EPSG selection and
bounding box from a set of geo-unit centroids.

Zone selection is pure arithmetic on the coordinate medians (borrowed from
``MAY2/.../world_map/projection/utm.py``), so it needs no projection library and
stays render-free (ADR-0002). The heavier lon/lat -> metre transform
(:func:`wgs84_to_utm`) lazy-imports ``pyproj`` only when actually called.

Coordinates throughout are ``{geo_unit_id: (lat, lon)}`` in WGS84, matching
``core/load_data/world`` ``World.geo_unit_coords()``.
"""

from __future__ import annotations

import statistics


def _zone_from_lon(lon: float) -> int:
    """UTM zone number (1-60) containing ``lon`` degrees."""
    return int((lon + 180) / 6) % 60 + 1


def _medians(coords: dict[int, tuple[float, float]]) -> tuple[float, float]:
    """``(median_lat, median_lon)`` over the coord values."""
    lats = [lat for lat, _ in coords.values()]
    lons = [lon for _, lon in coords.values()]
    return statistics.median(lats), statistics.median(lons)


def utm_zone(coords: dict[int, tuple[float, float]]) -> int:
    """UTM zone number from the *median* longitude — robust to stray outliers."""
    _, median_lon = _medians(coords)
    return _zone_from_lon(median_lon)


def utm_epsg(coords: dict[int, tuple[float, float]]) -> int:
    """EPSG code for the UTM zone, hemisphere chosen from the median latitude.

    Northern band ``32600 + zone``; southern ``32700 + zone``.
    """
    median_lat, median_lon = _medians(coords)
    zone = _zone_from_lon(median_lon)
    hemisphere_offset = 100 if median_lat < 0 else 0
    return 32600 + zone + hemisphere_offset


def bbox_from_coords(
    coords: dict[int, tuple[float, float]],
) -> dict[str, float]:
    """WGS84 bounding box ``{west, east, south, north}`` over all centroids."""
    lats = [lat for lat, _ in coords.values()]
    lons = [lon for _, lon in coords.values()]
    return {
        "west": min(lons),
        "east": max(lons),
        "south": min(lats),
        "north": max(lats),
    }


def wgs84_to_utm(lats, lons, epsg: int):
    """Project WGS84 lat/lon arrays to UTM easting/northing (metres).

    Lazy-imports ``pyproj`` (ADR-0002); ``epsg`` is a full UTM EPSG code as
    returned by :func:`utm_epsg`.
    """
    import numpy as np
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    eastings, northings = transformer.transform(np.asarray(lons), np.asarray(lats))
    return (
        np.asarray(eastings, dtype=np.float64),
        np.asarray(northings, dtype=np.float64),
    )
