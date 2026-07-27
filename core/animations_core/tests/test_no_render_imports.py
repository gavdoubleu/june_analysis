"""ADR-0002: heavy render deps stay lazy — two invariants.

(i) *Import-time purity*: importing ``core.animations_core`` (and building a
``RenderConfig`` + running the pure projection helpers) must pull in no
matplotlib / cartopy / pyproj / pillow / ffmpeg — the real ADR-0002 guarantee is
that ``import core`` works with them absent.

(ii) *Data-stage purity*: ``prepare()`` and touching the ``Prepared`` it returns
must not reach the *render* stack (matplotlib / cartopy / pillow / ffmpeg). This
is the ``Prepared``-is-render-free-data claim: the render deps enter only in
``Scene``. pyproj + scipy are deliberately *excluded* here — projecting and
smoothing are ``prepare()``'s own job, so it legitimately imports them at call
time (the import-time invariant above already proves ``import`` alone doesn't).
"""

import subprocess
import sys

_IMPORT_PROBE = """
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

# prepare() may load pyproj/scipy (its job); it must not load the render stack.
_PREPARE_PROBE = """
import sys
import numpy as np
from core.aggregate.aggregate import Aggregate
from core.animations_core import prepare, RenderConfig


class _World:
    def geo_unit_coords(self):
        return {10: (51.5, -0.1), 20: (51.6, -0.2)}

    def population_by_geo_unit(self):
        return {10: 2000, 20: 3000}

    def infer_missing_coordinates(self):
        return 2


aggregate = Aggregate(
    counts=np.arange(4, dtype="float64").reshape(2, 2),
    geo_unit_ids=np.array([10, 20], dtype=np.int64),
    bin_starts=np.arange(2, dtype="float64"),
    days_per_bin=1.0,
    event_type="infection",
)
prepared = prepare(aggregate, _World(), RenderConfig())
# Touch the data so lazy attribute access can't hide a render import.
_ = (prepared.smoothed_grids, prepared.vmin, prepared.vmax, prepared.metric_label)

forbidden = ("matplotlib", "cartopy", "PIL", "imageio_ffmpeg", "ffmpeg")
leaked = [m for m in forbidden if m in sys.modules]
print(",".join(leaked))
"""


def _run_probe(probe: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [name for name in result.stdout.strip().split(",") if name]


def test_import_and_use_pulls_in_no_render_deps():
    leaked = _run_probe(_IMPORT_PROBE)
    assert leaked == [], f"render deps leaked into sys.modules: {leaked}"


def test_prepare_pulls_in_no_render_deps():
    leaked = _run_probe(_PREPARE_PROBE)
    assert leaked == [], f"render deps leaked from prepare(): {leaked}"
