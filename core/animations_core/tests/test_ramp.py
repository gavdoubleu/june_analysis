"""Tracer 3: global normalisation + alpha colour ramp (visual_settings).

The colour scale is fixed across every frame (ADR-0006), so ``vmin/vmax`` are
computed once over *all* per-frame cell grids, NaN-aware (empty cells are NaN).
The ramp fades low values to transparent so the basemap shows through.
"""

import numpy as np
import pytest

from core.animations_core.visual_settings.ramp import (
    build_alpha_ramp,
    global_value_range,
)


def test_global_range_spans_all_frames_ignoring_nan():
    frame_a = np.array([[np.nan, 1.0], [2.0, np.nan]])
    frame_b = np.array([[5.0, np.nan], [np.nan, 3.0]])
    vmin, vmax = global_value_range([frame_a, frame_b])
    assert vmin == 0.0  # magnitude ramp floors at zero
    assert vmax == 5.0  # global max across both frames


def test_global_range_all_nan_is_degenerate_safe():
    # An all-empty stack must not yield vmin == vmax (which breaks Normalize).
    grids = [np.full((2, 2), np.nan)]
    vmin, vmax = global_value_range(grids)
    assert vmin < vmax


def test_alpha_ramp_fades_from_transparent_to_opaque():
    matplotlib = pytest.importorskip("matplotlib")
    cmap = build_alpha_ramp("magma", alpha_power=1.0)
    samples = cmap(np.linspace(0, 1, 256))
    assert samples[0, 3] == pytest.approx(0.0)  # low value -> transparent
    assert samples[-1, 3] == pytest.approx(1.0)  # high value -> opaque
