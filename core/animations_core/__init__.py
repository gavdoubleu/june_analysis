"""Render-agnostic map-animation engine (Phase 4a).

Consumes a dense ``core.aggregate.Aggregate`` + a ``core.load_data.world.World``
+ a :class:`RenderConfig`, and produces a per-geo density-heatmap animation
(ADR-0006 / ADR-0007). All heavy render deps (matplotlib, cartopy, pyproj,
pillow, ffmpeg) are lazy-imported inside functions, so ``import core`` succeeds
with them absent (ADR-0002).

Public surface: :class:`RenderConfig`, :func:`prepare` and the ``Prepared`` it
returns (``prepare(aggregate, world, config).write(path)``).
"""

from .build_animation.render import Prepared, prepare
from .config import RenderConfig

__all__ = ["Prepared", "RenderConfig", "prepare"]
