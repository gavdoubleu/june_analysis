"""Tracer 6: prepare() data pipeline + per-frame draw.

``prepare(aggregate, world, config)`` turns a dense per-geo Aggregate + a World
into a render-ready ``Prepared``: one smoothed cell grid per bin (Frame ==
Aggregate bin), a global colour scale, per-frame date labels and the UTM
geometry. It infers missing coordinates from the World, then *hard-errors* if any
unit carrying events still has no coordinate (the resolved policy — a map cannot
silently drop located events).

The prepare() half is pure data (numpy / pyproj / scipy), so it is tested without
matplotlib. The draw half needs matplotlib + cartopy and is skipped when absent.
"""

from datetime import date

import numpy as np
import pytest

pytest.importorskip("pyproj")
pytest.importorskip("scipy")

from core.aggregate.aggregate import Aggregate  # noqa: E402
from core.animations_core.config import RenderConfig  # noqa: E402
from core.animations_core.build_animation import render  # noqa: E402


class _FakeWorld:
    """Minimal World stand-in: coord + population maps, opt-in inference."""

    def __init__(self, coords, populations, *, inferable=None):
        self._coords = dict(coords)
        self._populations = dict(populations)
        self._inferable = dict(inferable or {})

    def geo_unit_coords(self):
        return dict(self._coords)

    def population_by_geo_unit(self):
        return dict(self._populations)

    def infer_missing_coordinates(self):
        self._coords.update(self._inferable)
        self._inferable = {}
        return len(self._coords)


def _aggregate(n_bins=3):
    geo_unit_ids = np.array([10, 20], dtype=np.int64)
    counts = np.arange(n_bins * 2, dtype="float64").reshape(n_bins, 2)
    bin_starts = np.arange(n_bins, dtype="float64")
    return Aggregate(
        counts=counts,
        geo_unit_ids=geo_unit_ids,
        bin_starts=bin_starts,
        days_per_bin=1.0,
        event_type="infection",
    )


def _world():
    # Two units a few km apart in UTM zone 30N (southern England-ish).
    return _FakeWorld(
        coords={10: (51.5, -0.1), 20: (51.6, -0.2)},
        populations={10: 2000, 20: 3000},
    )


def test_prepare_yields_one_grid_per_bin_with_global_scale():
    aggregate = _aggregate(n_bins=3)
    prepared = render.prepare(aggregate, _world(), RenderConfig())
    assert len(prepared.smoothed_grids) == 3  # Frame == bin
    assert prepared.vmin == 0.0
    assert prepared.vmax >= 0.0
    # Every grid shares the geometry.
    shapes = {grid.shape for grid in prepared.smoothed_grids}
    assert shapes == {prepared.grid_shape}


def test_prepare_bakes_the_metric_label():
    rate = render.prepare(
        _aggregate(n_bins=2), _world(), RenderConfig(metric="rate_per_100k")
    )
    assert rate.metric_label == "rate per 100k"
    count = render.prepare(
        _aggregate(n_bins=2), _world(), RenderConfig(metric="count")
    )
    assert count.metric_label == "count"


def test_prepare_dates_use_start_date_when_given():
    aggregate = _aggregate(n_bins=2)
    config = RenderConfig(start_date=date(2020, 3, 1))
    prepared = render.prepare(aggregate, _world(), config)
    assert prepared.frame_labels[0] == "2020-03-01"
    assert prepared.frame_labels[1] == "2020-03-02"


def test_prepare_labels_by_day_number_without_start_date():
    prepared = render.prepare(_aggregate(n_bins=2), _world(), RenderConfig())
    assert "0" in prepared.frame_labels[0]
    assert prepared.frame_labels[0] != prepared.frame_labels[1]


def test_prepare_infers_then_hard_errors_on_uncoordinated_unit():
    aggregate = _aggregate(n_bins=2)
    # Unit 20 has no coordinate and none inferable -> hard error.
    world = _FakeWorld(
        coords={10: (51.5, -0.1)},
        populations={10: 2000, 20: 3000},
    )
    with pytest.raises(ValueError, match="coordinate"):
        render.prepare(aggregate, world, RenderConfig())


def test_prepare_inference_supplies_missing_coordinate():
    aggregate = _aggregate(n_bins=2)
    world = _FakeWorld(
        coords={10: (51.5, -0.1)},
        populations={10: 2000, 20: 3000},
        inferable={20: (51.6, -0.2)},
    )
    prepared = render.prepare(aggregate, world, RenderConfig())
    assert len(prepared.smoothed_grids) == 2  # inference filled the gap


def test_config_projection_sets_the_axis_crs():
    pytest.importorskip("matplotlib")
    import cartopy.crs as ccrs
    import matplotlib

    matplotlib.use("Agg")

    config = RenderConfig(projection="platecarree")
    prepared = render.prepare(_aggregate(n_bins=2), _world(), config)
    scene, _mappable = prepared.build_layout()
    try:
        assert isinstance(scene.map_axis.projection, ccrs.PlateCarree)
    finally:
        import matplotlib.pyplot as plt

        plt.close(scene.figure)


def test_draw_frame_updates_heatmap_and_date_ticker():
    pytest.importorskip("matplotlib")
    pytest.importorskip("cartopy")
    import matplotlib

    matplotlib.use("Agg")

    prepared = render.prepare(_aggregate(n_bins=2), _world(), RenderConfig())
    scene, mappable = prepared.build_layout()
    try:
        prepared.draw_frame(scene, mappable, 0)
        assert len(scene.map_axis.images) >= 1  # heatmap layer present
        assert scene.date_text.get_text() == prepared.frame_labels[0]
        first_image = scene.heatmap_image
        prepared.draw_frame(scene, mappable, 1)
        # Same artist reused across frames (updated, not re-added).
        assert scene.heatmap_image is first_image
    finally:
        import matplotlib.pyplot as plt

        plt.close(scene.figure)
