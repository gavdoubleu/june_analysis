"""Tracer 4: basemap fetch, hash-keyed cache, blank fallback.

The basemap is a shaded-relief tile drawn under the heatmap. It is fetched once
per (bbox, zone, resolution) and cached on disk so re-renders and tests never hit
the network. When the fetch fails (offline) the render degrades to a blank
background, unless ``require_basemap`` forces a hard error.

The fetch itself is monkeypatched here, so these tests never touch ESRI.
"""

import numpy as np
import pytest

from core.animations_core.build_animation import basemap

UTM_BBOX = {"west": 0.0, "east": 100_000.0, "south": 0.0, "north": 120_000.0}
EPSG = 32630
FIGSIZE = (6.0, 8.0)
DPI = 100


def _fake_tile(*_args, **_kwargs):
    return np.full((16, 12, 3), 128, dtype=np.uint8)


def test_cache_key_is_stable_and_input_sensitive():
    key = basemap.basemap_cache_key(UTM_BBOX, EPSG, (1200, 1600))
    assert key == basemap.basemap_cache_key(UTM_BBOX, EPSG, (1200, 1600))
    other = basemap.basemap_cache_key(UTM_BBOX, 32631, (1200, 1600))
    assert key != other


def test_fetch_result_is_cached_and_reused(tmp_path, monkeypatch):
    calls = {"n": 0}

    def counting_tile(*args, **kwargs):
        calls["n"] += 1
        return _fake_tile()

    monkeypatch.setattr(basemap, "_fetch_esri_tile", counting_tile)

    first = basemap.load_basemap(
        UTM_BBOX, EPSG, FIGSIZE, DPI, cache_dir=str(tmp_path)
    )
    second = basemap.load_basemap(
        UTM_BBOX, EPSG, FIGSIZE, DPI, cache_dir=str(tmp_path)
    )
    assert calls["n"] == 1  # second call served from disk cache
    assert np.array_equal(first, second)


def test_offline_returns_blank_by_default(monkeypatch):
    def offline(*_args, **_kwargs):
        raise ConnectionError("no network")

    monkeypatch.setattr(basemap, "_fetch_esri_tile", offline)
    result = basemap.load_basemap(UTM_BBOX, EPSG, FIGSIZE, DPI)
    assert result is None  # blank background, render carries on


def test_offline_raises_when_basemap_required(monkeypatch):
    def offline(*_args, **_kwargs):
        raise ConnectionError("no network")

    monkeypatch.setattr(basemap, "_fetch_esri_tile", offline)
    with pytest.raises(Exception):
        basemap.load_basemap(
            UTM_BBOX, EPSG, FIGSIZE, DPI, require_basemap=True
        )
