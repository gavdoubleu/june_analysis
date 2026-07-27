"""ADR-0002: heavy render deps stay lazy. Importing ``core.animations_core``
(and building a ``RenderConfig`` + the pure projection helpers) must not pull in
matplotlib / cartopy / pyproj / pillow / ffmpeg — they are imported *inside* the
functions that need them, so ``import core`` works with them absent."""

import subprocess
import sys

_PROBE = """
import sys
import core.animations_core as ac
from core.animations_core.build_animation.projection import utm_zone, bbox_from_coords

coords = {1: (52.0, -1.5), 2: (53.1, -0.9)}
ac.RenderConfig()
utm_zone(coords)
bbox_from_coords(coords)

forbidden = ("matplotlib", "cartopy", "pyproj", "PIL", "imageio_ffmpeg", "ffmpeg")
leaked = [m for m in forbidden if m in sys.modules]
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
