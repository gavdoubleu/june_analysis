"""Tracer 4: basemap fetch, hash-keyed cache, style selection, blank fallback.

The basemap is a tile drawn under the heatmap, in the requested **Basemap style**.
It is fetched once per (bbox, zone, resolution, style) and cached on disk so
re-renders and tests never hit the network. When the fetch fails with a
network/HTTP error (offline) the render degrades to a blank background, unless
``require_basemap`` forces a hard error. Any other failure (a real bug) always
raises.

The fetch itself is monkeypatched here, so these tests never touch ESRI.
"""

import numpy as np
import pytest
import requests

from core.animations_core import RenderConfig
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


def test_cache_key_separates_styles():
    """Two styles of the same bbox are different images — never the same file."""
    relief = basemap.basemap_cache_key(UTM_BBOX, EPSG, (1200, 1600), "shaded_relief")
    street = basemap.basemap_cache_key(UTM_BBOX, EPSG, (1200, 1600), "street")
    assert relief != street


def test_requested_style_reaches_the_export_url(monkeypatch):
    """The style's MapServer service, not the default, is what gets requested."""
    requested = {}

    class _Response:
        content = b""

        def raise_for_status(self):
            pass

    def capture(url, **_kwargs):
        requested["url"] = url
        return _Response()

    monkeypatch.setattr(requests, "get", capture)
    monkeypatch.setattr(
        "PIL.Image.open", lambda *_a, **_k: _FakeImage(),
    )

    basemap._fetch_esri_tile(UTM_BBOX, EPSG, (10, 10), "street")
    assert "World_Street_Map/MapServer/export" in requested["url"]
    assert f"bboxSR={EPSG}&imageSR={EPSG}" in requested["url"]


def test_unknown_style_is_rejected_at_config_load():
    """A typo fails before any events are read, not after a full aggregate."""
    with pytest.raises(ValueError, match="unknown basemap_style"):
        RenderConfig(basemap_style="streets")


def test_unknown_style_never_reaches_the_network(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("fetch attempted for an unknown style")

    monkeypatch.setattr(basemap, "_fetch_esri_tile", unexpected)
    with pytest.raises(ValueError, match="unknown basemap_style"):
        basemap.load_basemap(UTM_BBOX, EPSG, FIGSIZE, DPI, style="nope")


def test_every_style_carries_a_credit_line():
    """Licence obligation: no style may be drawable without attribution."""
    assert all(style.attribution for style in basemap.BASEMAP_STYLES.values())


class _FakeImage:
    """Stand-in for a decoded PIL image (``convert`` then ``np.asarray``)."""

    def convert(self, _mode):
        return np.full((4, 4, 3), 7, dtype=np.uint8)


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
        raise requests.exceptions.ConnectionError("no network")

    monkeypatch.setattr(basemap, "_fetch_esri_tile", offline)
    result = basemap.load_basemap(UTM_BBOX, EPSG, FIGSIZE, DPI)
    assert result is None  # blank background, render carries on


def test_offline_raises_when_basemap_required(monkeypatch):
    def offline(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("no network")

    monkeypatch.setattr(basemap, "_fetch_esri_tile", offline)
    with pytest.raises(Exception):
        basemap.load_basemap(
            UTM_BBOX, EPSG, FIGSIZE, DPI, require_basemap=True
        )


def test_non_network_error_always_propagates(monkeypatch):
    def buggy(*_args, **_kwargs):
        raise KeyError("west")

    monkeypatch.setattr(basemap, "_fetch_esri_tile", buggy)
    with pytest.raises(KeyError):
        basemap.load_basemap(UTM_BBOX, EPSG, FIGSIZE, DPI, require_basemap=False)
