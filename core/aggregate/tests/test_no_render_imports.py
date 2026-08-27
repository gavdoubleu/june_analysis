"""ADR-0002: no render deps below the core boundary. Importing core.aggregate /
core.load_data.geo_events (and exercising them) must not pull in matplotlib /
ffmpeg / cartopy."""

import subprocess
import sys

_FORBIDDEN = ("matplotlib", "cartopy", "imageio_ffmpeg", "ffmpeg")

# Run in a clean interpreter so nothing another test imported can mask a leak.
_PROBE = """
import sys
import numpy as np, pandas as pd
import core.aggregate as agg
import core.aggregate.rollup as rollup
import core.aggregate.trailing_window as trailing_window
import core.load_data.geo_events  # noqa: F401 — must import render-free too

events = pd.DataFrame({
    "time": [0.1, 1.2, 1.8],
    "geo_unit_id": [1, 1, 2],
})
aggregate = agg.aggregate_events(events, event_type="infections")
agg.epidemic_curve(aggregate)
agg.to_long_dataframe(aggregate)
# rollup/trailing_window aren't exported from core.aggregate, so the import
# above doesn't reach them — exercise both explicitly.
rollup.rollup(aggregate, ancestor_by_geo_unit={1: 1, 2: 1})
trailing_window.trailing_mean(aggregate, window_days=1.0)

leaked = [m for m in ("matplotlib", "cartopy", "imageio_ffmpeg", "ffmpeg")
          if m in sys.modules]
print(",".join(leaked))
"""


def test_import_and_use_pulls_in_no_render_deps():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    leaked = [name for name in result.stdout.strip().split(",") if name]
    assert leaked == [], f"render deps leaked into sys.modules: {leaked}"
