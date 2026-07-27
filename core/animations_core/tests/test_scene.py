"""Scene: the stateful render surface built beside the old Prepared path.

``Scene(prepared, config)`` owns all matplotlib — it builds the static figure
(map axis + extent, colourbar on the global scale, basemap) in ``__init__``,
updates one reused heatmap artist per frame via :meth:`draw_frame`, and encodes
through :func:`writers.encode` from a heavy-dep-free ``AnimationSource``. The
render stack is skipped when matplotlib/cartopy are absent (ADR-0002).

Basemap fetch is stubbed to ``None`` throughout so the tests stay offline and
deterministic (the fetch/cache path is exercised by ``test_basemap``).
"""

import dataclasses
from datetime import date

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
pytest.importorskip("cartopy")

from core.aggregate.aggregate import Aggregate  # noqa: E402
from core.animations_core.build_animation import render, writers  # noqa: E402
from core.animations_core.build_animation import basemap as basemap_module  # noqa: E402
from core.animations_core.build_animation.scene import Scene  # noqa: E402
from core.animations_core.config import RenderConfig  # noqa: E402


class _FakeWorld:
    def geo_unit_coords(self):
        return {10: (51.5, -0.1), 20: (51.6, -0.2)}

    def population_by_geo_unit(self):
        return {10: 2000, 20: 3000}

    def infer_missing_coordinates(self):
        return 2


def _aggregate(n_bins=2):
    return Aggregate(
        counts=np.arange(n_bins * 2, dtype="float64").reshape(n_bins, 2),
        geo_unit_ids=np.array([10, 20], dtype=np.int64),
        bin_starts=np.arange(n_bins, dtype="float64"),
        days_per_bin=1.0,
        event_type="infection",
    )


def _prepared(n_bins=2, **config_kwargs):
    config = RenderConfig(**config_kwargs)
    return render.prepare(_aggregate(n_bins), _FakeWorld(), config)


@pytest.fixture(autouse=True)
def _no_basemap_fetch(monkeypatch):
    """Keep the basemap layer empty so no test touches the network."""
    monkeypatch.setattr(basemap_module, "load_basemap", lambda *a, **k: None)


def _scene(n_bins=2, **config_kwargs):
    config = RenderConfig(**config_kwargs)
    prepared = render.prepare(_aggregate(n_bins), _FakeWorld(), config)
    return Scene(prepared, config)


def _close(scene):
    import matplotlib.pyplot as plt

    plt.close(scene.figure)


# --- 1: static scene, map axis extent ------------------------------------
def test_scene_map_axis_extent_matches_utm_bbox():
    prepared = _prepared()
    scene = Scene(prepared, RenderConfig())
    try:
        west, east, south, north = scene.figure.axes[0].get_extent()
        assert west == pytest.approx(prepared.utm_bbox["west"], abs=1.0)
        assert east == pytest.approx(prepared.utm_bbox["east"], abs=1.0)
        assert south == pytest.approx(prepared.utm_bbox["south"], abs=1.0)
        assert north == pytest.approx(prepared.utm_bbox["north"], abs=1.0)
    finally:
        _close(scene)


# --- 2: projection defaults to UTM, pluggable ----------------------------
def test_axis_projection_defaults_to_utm_but_is_pluggable():
    import cartopy.crs as ccrs

    default_scene = _scene()
    plate_scene = _scene(projection="platecarree")
    try:
        assert isinstance(default_scene.figure.axes[0].projection, ccrs.UTM)
        assert isinstance(plate_scene.figure.axes[0].projection, ccrs.PlateCarree)
    finally:
        _close(default_scene)
        _close(plate_scene)


# --- 2b: a named non-UTM projection (mercator) is selected ---------------
def test_mercator_projection_selected_by_name():
    import cartopy.crs as ccrs

    scene = _scene(projection="mercator")
    try:
        assert isinstance(scene.figure.axes[0].projection, ccrs.Mercator)
    finally:
        _close(scene)


# --- 3: unknown projection rejected --------------------------------------
def test_unknown_projection_raises():
    with pytest.raises(ValueError, match="projection"):
        _scene(projection="bananas")


# --- 4: basemap no-op adds no image --------------------------------------
def test_no_basemap_adds_no_image():
    scene = _scene()  # fixture stubs load_basemap -> None
    try:
        assert len(scene.figure.axes[0].images) == 0
    finally:
        _close(scene)


# --- 4b: a supplied basemap array is drawn beneath the heatmap -----------
def test_basemap_array_is_drawn_beneath_the_heatmap(monkeypatch):
    basemap_array = np.full((8, 6, 3), 100, dtype=np.uint8)
    monkeypatch.setattr(
        basemap_module, "load_basemap", lambda *a, **k: basemap_array
    )
    scene = _scene()  # basemap drawn in __init__, before any frame
    try:
        images = scene.figure.axes[0].images
        assert len(images) == 1
        assert images[0].zorder == 0  # sits under the heatmap layer
    finally:
        _close(scene)


# --- 5: colourbar spans the global scale ---------------------------------
def test_colourbar_uses_the_global_scale():
    prepared = _prepared()
    scene = Scene(prepared, RenderConfig())
    try:
        assert scene._mappable.get_clim() == (prepared.vmin, prepared.vmax)
    finally:
        _close(scene)


# --- 5b: colourbar label reads prepared.metric_label ---------------------
def test_colourbar_label_reads_prepared_metric_label():
    # Sentinel label distinguishes reading the derived field from re-deriving
    # off config.metric (which would map to "rate per 100k").
    prepared = dataclasses.replace(_prepared(), metric_label="SENTINEL")
    scene = Scene(prepared, RenderConfig())
    try:
        assert scene.figure.axes[1].get_ylabel() == "SENTINEL"
    finally:
        _close(scene)


# --- 6: draw_frame sets, then reuses, the heatmap artist -----------------
def test_draw_frame_sets_then_reuses_the_heatmap_artist():
    scene = _scene(n_bins=2, start_date=date(2020, 3, 1))
    try:
        scene.draw_frame(0)
        map_axis = scene.figure.axes[0]
        assert len(map_axis.images) == 1  # heatmap layer added
        assert map_axis.texts[0].get_text() == "2020-03-01"
        scene.draw_frame(1)
        # Artist reused (data swapped), not re-added.
        assert len(map_axis.images) == 1
        assert map_axis.texts[0].get_text() == "2020-03-02"
    finally:
        _close(scene)


# --- 7: save writes non-empty gif + png ----------------------------------
def test_save_writes_gif_and_png(tmp_path):
    pytest.importorskip("PIL")

    gif = tmp_path / "anim.gif"
    _scene().save(str(gif))
    assert gif.exists() and gif.stat().st_size > 0

    png = tmp_path / "still.png"
    _scene().save(str(png))
    assert png.exists() and png.stat().st_size > 0


# --- 8: encode streams draw() one frame at a time ------------------------
def test_encode_streams_draw_per_frame(tmp_path):
    pytest.importorskip("PIL")
    from matplotlib.figure import Figure

    figure = Figure()
    figure.add_subplot(1, 1, 1)
    drawn = []
    source = writers.AnimationSource(
        figure=figure,
        frame_count=3,
        draw=drawn.append,
        fps=5,
        dpi=60,
    )
    writers.encode(source, str(tmp_path / "streamed.gif"))
    # Every frame drawn on demand (never all pre-built); each index visited.
    assert set(drawn) == {0, 1, 2}
