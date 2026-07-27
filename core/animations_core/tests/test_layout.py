"""Tracer 5: static figure scaffold (map axis + colourbar + date ticker).

The layout builds the parts that do not change between frames: a cartopy
``GeoAxes`` map axis whose extent is the UTM bounding box, a fixed colourbar for
the global scale, an optional title, and a date-text artist the frame loop
rewrites per frame. The map axis is a GeoAxes (not a plain Axes) so its
projection is pluggable — the UTM-metre layers are drawn with ``transform =
data_crs`` and reproject onto whatever axis CRS is chosen. The per-frame
heatmap/basemap layers are drawn by the caller.

matplotlib + cartopy are heavy deps (ADR-0002), so they are skipped when absent.
"""

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
pytest.importorskip("cartopy")

from core.animations_core.build_animation import layout  # noqa: E402
from core.animations_core.visual_settings.ramp import build_alpha_ramp  # noqa: E402

UTM_BBOX = {"west": 400_000.0, "east": 500_000.0, "south": 5_700_000.0, "north": 5_820_000.0}
EPSG = 32630  # UTM zone 30N


def test_layout_map_axis_extent_matches_utm_bbox():
    scene = layout.create_layout((6.0, 8.0), 100, UTM_BBOX, EPSG, title="Infections")
    try:
        west, east, south, north = scene.map_axis.get_extent(crs=scene.data_crs)
        assert west == pytest.approx(UTM_BBOX["west"], abs=1.0)
        assert east == pytest.approx(UTM_BBOX["east"], abs=1.0)
        assert south == pytest.approx(UTM_BBOX["south"], abs=1.0)
        assert north == pytest.approx(UTM_BBOX["north"], abs=1.0)
    finally:
        _close(scene)


def test_axis_projection_defaults_to_data_utm_but_is_pluggable():
    import cartopy.crs as ccrs

    default_scene = layout.create_layout((6.0, 8.0), 100, UTM_BBOX, EPSG)
    plate = ccrs.PlateCarree()
    custom_scene = layout.create_layout(
        (6.0, 8.0), 100, UTM_BBOX, EPSG, projection=plate
    )
    try:
        # Default axis CRS is the UTM data CRS; an override takes effect.
        assert default_scene.map_axis.projection == default_scene.data_crs
        assert custom_scene.map_axis.projection == plate
    finally:
        _close(default_scene)
        _close(custom_scene)


def test_crs_from_name_resolves_named_projections_and_default():
    import cartopy.crs as ccrs

    assert layout.crs_from_name(None) is None  # default -> data UTM
    assert layout.crs_from_name("utm") is None  # explicit UTM -> data CRS
    assert isinstance(layout.crs_from_name("PlateCarree"), ccrs.PlateCarree)
    assert isinstance(layout.crs_from_name("mercator"), ccrs.Mercator)


def test_crs_from_name_rejects_unknown():
    with pytest.raises(ValueError, match="projection"):
        layout.crs_from_name("bananas")


def test_date_text_is_rewritable_by_the_frame_loop():
    scene = layout.create_layout((6.0, 8.0), 100, UTM_BBOX, EPSG)
    try:
        scene.date_text.set_text("2020-03-14")
        assert scene.date_text.get_text() == "2020-03-14"
    finally:
        _close(scene)


def test_draw_basemap_none_adds_no_image():
    scene = layout.create_layout((6.0, 8.0), 100, UTM_BBOX, EPSG)
    try:
        layout.draw_basemap(scene.map_axis, None, UTM_BBOX, scene.data_crs)
        assert len(scene.map_axis.images) == 0
        layout.draw_basemap(
            scene.map_axis,
            np.full((8, 6, 3), 100, dtype=np.uint8),
            UTM_BBOX,
            scene.data_crs,
        )
        assert len(scene.map_axis.images) == 1
    finally:
        _close(scene)


def test_colourbar_uses_the_global_scale():
    scene = layout.create_layout((6.0, 8.0), 100, UTM_BBOX, EPSG)
    try:
        cmap = build_alpha_ramp("magma", 1.0)
        mappable = layout.add_colourbar(
            scene.figure, scene.colourbar_axis, cmap, 0.0, 250.0,
            label="rate per 100k",
        )
        assert mappable.get_clim() == (0.0, 250.0)
    finally:
        _close(scene)


def _close(scene):
    import matplotlib.pyplot as plt

    plt.close(scene.figure)
