"""Render-agnostic map-animation engine (Phase 4a).

Consumes a dense ``core.aggregate.Aggregate`` + a ``core.load_data.world.World``
+ a :class:`RenderConfig`, and produces a per-geo density-heatmap animation
(ADR-0006 / ADR-0007). All heavy render deps (matplotlib, cartopy, pyproj,
pillow, ffmpeg) are lazy-imported inside functions, so ``import core`` succeeds
with them absent (ADR-0002).

Public surface: :func:`animate` (the one-liner), plus the two-step it composes —
:func:`prepare` returning render-free :class:`Prepared` data, and :class:`Scene`
owning the render (``Scene(prepare(aggregate, world, config), config).save(path)``);
:class:`RenderConfig` carries the knobs.
"""

from .build_animation.render import Prepared, prepare
from .build_animation.scene import Scene
from .config import RenderConfig

__all__ = ["Prepared", "RenderConfig", "Scene", "animate", "prepare"]


def animate(aggregate, world, config: RenderConfig, path: str, fmt=None) -> None:
    """Prepare then render an animation to ``path`` in one call.

    Convenience over the ``prepare`` -> ``Scene`` two-step for the common case of
    a single output; drop to the two-step to drive several ``Scene``s (different
    cosmetics) off one ``prepare()``. Format is guessed from the extension unless
    ``fmt`` is given.
    """
    Scene(prepare(aggregate, world, config), config).save(path, fmt)
