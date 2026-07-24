"""ADR-0002: no render deps below the core boundary. Importing core.aggregate
(and exercising it) must not pull in matplotlib / ffmpeg / cartopy."""

import subprocess
import sys

_FORBIDDEN = ("matplotlib", "cartopy", "imageio_ffmpeg", "ffmpeg")

# Run in a clean interpreter so nothing another test imported can mask a leak.
_PROBE = """
import sys
import numpy as np, pandas as pd
import core.aggregate as agg

events = pd.DataFrame({
    "time": [0.1, 1.2, 1.8],
    "venue_geo_unit_id": [1, 1, 2],
    "person_geo_unit_id": [2, 2, 1],
})
aggregate = agg.aggregate_events(events, event_type="infections")
agg.epidemic_curve(aggregate)
agg.to_long_dataframe(aggregate)

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
