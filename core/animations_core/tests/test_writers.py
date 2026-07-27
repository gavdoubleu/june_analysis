"""Tracer 7: format registry + Prepared.write end-to-end.

``write(path, format=None)`` keys a writer registry (mirroring the projection
``@register`` idea): ``mp4`` / ``gif`` / ``png``, with the format guessed from the
path extension when omitted. png and gif are exercised for real (they need only
matplotlib + Pillow); mp4 needs ffmpeg, so only its registration + resolution are
asserted here.
"""

import numpy as np
import pytest

from core.animations_core.build_animation import writers


def test_register_holds_the_three_formats():
    assert set(writers.supported_formats()) >= {"mp4", "gif", "png"}


def test_resolve_format_guesses_extension_then_explicit_wins():
    assert writers.resolve_format("out/anim.gif", None) == "gif"
    assert writers.resolve_format("out/anim.mp4", None) == "mp4"
    # Explicit format overrides the extension.
    assert writers.resolve_format("out/anim.dat", "png") == "png"


def test_resolve_format_rejects_unknown():
    with pytest.raises(ValueError, match="format"):
        writers.resolve_format("out/anim.webm", None)


def test_set_gif_play_once_strips_netscape_loop_block():
    marker = b"\x21\xff\x0b" + b"NETSCAPE2.0"
    data = bytearray(b"GIF89a" + marker + b"\x03\x01\x00\x00\x00tail")
    stripped = writers._strip_netscape_loop(bytes(data))
    assert marker not in stripped
    assert stripped.endswith(b"tail")


def _prepared(n_bins=2):
    from datetime import date

    from core.aggregate.aggregate import Aggregate
    from core.animations_core.config import RenderConfig
    from core.animations_core.build_animation import render

    class _World:
        def geo_unit_coords(self):
            return {10: (51.5, -0.1), 20: (51.6, -0.2)}

        def population_by_geo_unit(self):
            return {10: 2000, 20: 3000}

        def infer_missing_coordinates(self):
            return 2

    aggregate = Aggregate(
        counts=np.arange(n_bins * 2, dtype="float64").reshape(n_bins, 2),
        geo_unit_ids=np.array([10, 20], dtype=np.int64),
        bin_starts=np.arange(n_bins, dtype="float64"),
        days_per_bin=1.0,
        event_type="infection",
    )
    config = RenderConfig(start_date=date(2020, 3, 1), fps=5, dpi=60)
    return render.prepare(aggregate, _World(), config)


def test_write_png_produces_a_static_file(tmp_path):
    pytest.importorskip("matplotlib")
    pytest.importorskip("cartopy")
    import matplotlib

    matplotlib.use("Agg")

    out = tmp_path / "still.png"
    _prepared().write(str(out))
    assert out.exists() and out.stat().st_size > 0


def test_write_gif_produces_an_animation(tmp_path):
    pytest.importorskip("matplotlib")
    pytest.importorskip("cartopy")
    pytest.importorskip("PIL")
    import matplotlib

    matplotlib.use("Agg")

    out = tmp_path / "anim.gif"
    _prepared().write(str(out))
    assert out.exists() and out.stat().st_size > 0
