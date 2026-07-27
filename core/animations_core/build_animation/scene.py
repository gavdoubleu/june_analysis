"""Stateful render surface for the animation (ADR-0002/0007).

``Scene(prepared, config)`` owns all matplotlib: it builds the static figure in
``__init__`` (map ``GeoAxes`` + extent, colourbar on the global scale, basemap,
date-text) and holds the reused ``heatmap_image`` as instance state. The one
public verb is :meth:`save`, which bundles a heavy-dep-free
:class:`~.writers.AnimationSource` and hands it to :func:`writers.encode` — the
dependency points one way (``Scene -> writers``), the sink never reaches back.

``Prepared`` is pure render-free data; the render stack (matplotlib + cartopy +
Pillow) enters only here, lazy-imported inside the methods (ADR-0002).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import layout as layout_module

if TYPE_CHECKING:
    from ..config import RenderConfig
    from .render import Prepared


class Scene:
    """Render-ready figure for one animation; :meth:`save` encodes it.

    The static scene is built once in ``__init__`` from the ``Prepared`` data +
    the render-only ``RenderConfig`` knobs; the same ``Prepared`` can drive
    several ``Scene``s with different cosmetics without re-running ``prepare()``.
    """

    def __init__(self, prepared: Prepared, config: RenderConfig) -> None:
        from ..visual_settings.ramp import build_alpha_ramp

        self._prepared = prepared
        self._config = config

        cmap = build_alpha_ramp(config.ramp, config.alpha_power)
        self._layout = layout_module.create_layout(
            prepared.figsize,
            config.dpi,
            prepared.utm_bbox,
            prepared.epsg,
            projection=layout_module.crs_from_name(config.projection),
            title=config.title,
        )
        layout_module.draw_basemap(
            self._layout.map_axis,
            self._load_basemap(),
            prepared.utm_bbox,
            self._layout.data_crs,
        )
        self._mappable = layout_module.add_colourbar(
            self._layout.figure,
            self._layout.colourbar_axis,
            cmap,
            prepared.vmin,
            prepared.vmax,
            label=prepared.metric_label,
        )

    @property
    def figure(self):
        """The matplotlib ``Figure`` — the encoder's render target."""
        return self._layout.figure

    def save(self, path: str, fmt: str | None = None) -> None:
        """Encode the animation to ``path`` (format guessed from the extension).

        Bundles an :class:`~.writers.AnimationSource` (figure + frame count + the
        bound :meth:`draw_frame` + fps/dpi) and delegates to
        :func:`writers.encode`; frames stream one at a time.
        """
        from . import writers

        source = writers.AnimationSource(
            figure=self._layout.figure,
            frame_count=len(self._prepared.smoothed_grids),
            draw=self.draw_frame,
            fps=self._config.fps,
            dpi=self._config.dpi,
        )
        writers.encode(source, path, fmt)

    def draw_frame(self, index: int) -> None:
        """Draw frame ``index``: update the heatmap layer and the date ticker.

        The heatmap ``AxesImage`` is created on the first call and reused (its
        data swapped) thereafter, so the encoder updates one artist per frame.
        """
        layout = self._layout
        grid = self._prepared.smoothed_grids[index]
        utm_bbox = self._prepared.utm_bbox
        extent = (
            utm_bbox["west"],
            utm_bbox["east"],
            utm_bbox["south"],
            utm_bbox["north"],
        )
        if layout.heatmap_image is None:
            layout.heatmap_image = layout.map_axis.imshow(
                grid,
                extent=extent,
                origin="upper",
                transform=layout.data_crs,
                cmap=self._mappable.cmap,
                norm=self._mappable.norm,
                zorder=1,
            )
        else:
            layout.heatmap_image.set_data(grid)
        layout.date_text.set_text(self._prepared.frame_labels[index])

    def _load_basemap(self):
        """Custom ``background_image`` if set, else the fetched/cached ESRI tile."""
        from . import basemap as basemap_module

        config = self._config
        prepared = self._prepared
        if config.background_image is not None:
            import numpy as _np
            from PIL import Image

            return _np.asarray(
                Image.open(config.background_image).convert("RGB")
            )
        return basemap_module.load_basemap(
            prepared.utm_bbox,
            prepared.epsg,
            prepared.figsize,
            config.dpi,
            cache_dir=config.cache_dir,
            require_basemap=config.require_basemap,
        )
