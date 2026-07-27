"""Tracer 1: pure projection maths — UTM zone + bbox from coord medians.

No render deps: zone selection is arithmetic on lon/lat medians (borrowed from
MAY2 ``world_map/projection/utm.py``); bbox is the coord min/max. These frame
every downstream raster/basemap step, so they are tested standalone.
"""

from core.animations_core.build_animation.projection import (
    bbox_from_coords,
    utm_epsg,
    utm_zone,
)


def test_utm_zone_from_england_coords():
    # England sits around lon -1.5, lat 52 -> UTM zone 30, northern hemisphere.
    coords = {1: (52.0, -1.5), 2: (53.1, -0.9), 3: (51.4, -2.2)}
    assert utm_zone(coords) == 30
    assert utm_epsg(coords) == 32630  # 32600 + zone, northern


def test_utm_zone_uses_median_not_outlier():
    # A single far-east outlier must not drag the zone; median lon decides.
    coords = {1: (52.0, -1.5), 2: (52.0, -1.4), 3: (52.0, -1.6), 4: (52.0, 30.0)}
    assert utm_zone(coords) == 30


def test_utm_epsg_southern_hemisphere():
    # Negative median lat -> southern band (32700 + zone).
    coords = {1: (-33.9, 18.4), 2: (-34.1, 18.6)}  # Cape Town ~ zone 34S
    assert utm_zone(coords) == 34
    assert utm_epsg(coords) == 32734


def test_bbox_from_coords_is_min_max():
    coords = {1: (52.0, -1.5), 2: (53.1, -0.9), 3: (51.4, -2.2)}
    bbox = bbox_from_coords(coords)
    assert bbox == {"west": -2.2, "east": -0.9, "south": 51.4, "north": 53.1}
