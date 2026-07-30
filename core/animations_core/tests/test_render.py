"""Tracer 6: prepare() data pipeline + per-frame draw.

``prepare(aggregate, world, config)`` turns a dense per-geo Aggregate + a World
into a render-ready ``Prepared``: one smoothed cell grid per bin (Frame ==
Aggregate bin), a global colour scale, per-frame date labels and the UTM
geometry. It infers missing coordinates from the World, then *hard-errors* if any
unit carrying events still has no coordinate (the resolved policy — a map cannot
silently drop located events).

``prepare()`` is pure data (numpy / pyproj / scipy), so it is tested without
matplotlib; the render half now lives on :class:`~.scene.Scene` (``test_scene``).
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


def test_prepare_states_the_trailing_window_in_the_metric_label():
    # A windowed frame shows a multi-day mean under a single "as of" date, so
    # the colourbar — where units live — has to say so. Derived from the
    # Aggregate, not a config knob, so it cannot fall out of sync.
    windowed = Aggregate(
        counts=np.arange(6, dtype="float64").reshape(3, 2),
        geo_unit_ids=np.array([10, 20], dtype=np.int64),
        bin_starts=np.arange(3, dtype="float64"),
        days_per_bin=1.0,
        event_type="infection",
        window_days=7.0,
    )

    prepared = render.prepare(windowed, _world(), RenderConfig(metric="rate_per_100k"))

    assert prepared.metric_label == "rate per 100k (7-day mean)"


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


def test_prepared_is_pure_data_without_config():
    # Prepared holds no render intent — the config blob does not ride along.
    prepared = render.prepare(_aggregate(n_bins=2), _world(), RenderConfig())
    assert not hasattr(prepared, "config")


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


def test_bbox_margin_keeps_every_unit_inside_the_grid():
    # Raw min/max put the south/east-most units on the boundary, where they
    # floor to row==height / col==width and are discarded. The margin fixes that.
    from core.animations_core.build_animation.raster import compute_cell_indices

    eastings = np.array([0.0, 1000.0])
    northings = np.array([0.0, 1000.0])
    bbox = render._bounding_box(eastings, northings)
    flat = compute_cell_indices(eastings, northings, bbox, grid_shape=(4, 4))
    assert np.all(flat >= 0)  # no unit dropped to -1


def test_prepare_hard_errors_on_unit_with_events_but_no_population():
    aggregate = _aggregate(n_bins=2)  # both units carry events
    world = _FakeWorld(
        coords={10: (51.5, -0.1), 20: (51.6, -0.2)},
        populations={10: 2000},  # unit 20 unpopulated
    )
    with pytest.raises(ValueError, match="population"):
        render.prepare(aggregate, world, RenderConfig(metric="rate_per_100k"))


def test_prepare_count_metric_tolerates_missing_population():
    aggregate = _aggregate(n_bins=2)
    world = _FakeWorld(
        coords={10: (51.5, -0.1), 20: (51.6, -0.2)},
        populations={10: 2000},  # count metric ignores population
    )
    prepared = render.prepare(aggregate, world, RenderConfig(metric="count"))
    assert len(prepared.smoothed_grids) == 2


def test_sub_day_bins_get_distinct_labels():
    # days_per_bin=0.5 -> bin_starts [0.0, 0.5]; int() truncation collapsed both.
    aggregate = _aggregate(n_bins=2)
    aggregate = Aggregate(
        counts=aggregate.counts,
        geo_unit_ids=aggregate.geo_unit_ids,
        bin_starts=np.array([0.0, 0.5]),
        days_per_bin=0.5,
        event_type="infection",
    )
    day = render.prepare(aggregate, _world(), RenderConfig())
    assert day.frame_labels == ["Day 0", "Day 0.5"]
    dated = render.prepare(
        aggregate, _world(), RenderConfig(start_date=date(2020, 3, 1))
    )
    assert dated.frame_labels[0] != dated.frame_labels[1]
    assert dated.frame_labels[0] == "2020-03-01"
