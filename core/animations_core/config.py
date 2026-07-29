"""Typed cosmetic-render configuration for the animator (Phase 4a schema).

``RenderConfig`` is the single place the engine's non-inferable knobs live, each
with a sensible default. 4a is tested against plain ``RenderConfig`` objects; the
4b driver loads a ``config.yaml`` and overrides these fields (several preset-style
YAMLs may overlay the same schema — plague is a Preset, never the default).

Inferable quantities (bbox, UTM zone, geo units, bin dates) are *not* here — they
come from the ``Aggregate`` + ``World``. Only cosmetics live in config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

_DEFAULT_CACHE_DIR = str(Path(__file__).parent / ".cache" / "basemaps")


@dataclass(frozen=True)
class RenderConfig:
    """Cosmetic knobs for a single animation render.

    Defaults are the ``config_default`` values; a Preset overrides any subset.
    """

    # --- what scalar the map encodes ---------------------------------------
    metric: str = "rate_per_100k"  # or "count"

    # --- colour ------------------------------------------------------------
    ramp: str = "inferno"  # fiery black->red->orange->yellow; still perceptually
    # uniform and colourblind-safe. Both presets already override magma to this.
    alpha_power: float = 1.0  # <1 faster onset, >1 only-opaque-near-max

    # --- spatial grid / smoothing (density heatmap) ------------------------
    grid_resolution: float = 1.0  # cells per km (UTM); tune per render
    sigma: float = 2.0  # Gaussian smoothing, grid-cell units

    # --- map projection ----------------------------------------------------
    projection: str | None = None  # axis CRS name; None -> UTM (the data CRS)

    # --- figure / output ---------------------------------------------------
    figure_height: float = 8.0  # inches; width derived from bbox aspect
    fps: int = 2  # at the default days_per_frame: 1, two simulated days per second
    dpi: int = 120
    formats: tuple[str, ...] = ("mp4", "gif")

    # --- labelling ---------------------------------------------------------
    start_date: date | None = None  # bin_start days added to this -> real dates
    title: str | None = None

    # --- basemap -----------------------------------------------------------
    background_image: str | None = None  # custom image path (bypasses fetch)
    require_basemap: bool = False  # True -> fetch failure is a hard error
    cache_dir: str | None = None  # None -> _DEFAULT_CACHE_DIR (repo-local, no opt-out)

    def __post_init__(self) -> None:
        if self.cache_dir is None:
            object.__setattr__(self, "cache_dir", _DEFAULT_CACHE_DIR)
