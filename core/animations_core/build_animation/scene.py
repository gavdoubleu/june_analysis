"""Stateful render surface for the animation (ADR-0002/0007).

``Scene(prepared, config)`` owns all matplotlib: it builds the static figure in
``__init__`` (map ``GeoAxes`` + extent, colourbar on the global scale, basemap +
its credit line, date-text) and holds the reused ``heatmap_image`` as instance state. The one
public verb is :meth:`save`, which bundles a heavy-dep-free
:class:`~.writers.AnimationSource` and hands it to :func:`writers.encode` — the
dependency points one way (``Scene -> writers``), the sink never reaches back.

The static-scaffold builders (map ``GeoAxes`` + extent, basemap layer, colourbar,
projection resolution) are absorbed here as module-private helpers: they are the
render half and have no caller but ``Scene``. The map axis is a ``GeoAxes`` so
its *projection is pluggable* — the heatmap is always UTM metres, drawn with
``transform=data_crs`` (a ``ccrs.UTM``); the axis projection defaults to that
same UTM CRS but can be reprojected onto a real backdrop's CRS.

``Prepared`` is pure render-free data; the render stack (matplotlib + cartopy +
Pillow) enters only here, lazy-imported inside the helpers (ADR-0002).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import RenderConfig
    from .render import Prepared


@dataclass
class _Layout:
    """The static figure scaffold shared by every frame (Scene-internal).

    ``data_crs`` is the CRS of the UTM-metre layers (basemap, heatmap); it is the
    ``transform`` used when drawing them, so they land correctly whatever the
    :attr:`map_axis` projection is.
    """

    figure: Any
    map_axis: Any
    colourbar_axis: Any
    date_text: Any
    data_crs: Any
    heatmap_image: Any = None  # the per-frame layer, created on first draw


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
        self._layout = _create_layout(
            prepared.figsize,
            config.dpi,
            prepared.utm_bbox,
            prepared.epsg,
            projection=_crs_from_name(config.projection),
            title=config.title,
        )
        basemap_array, is_fetched = self._load_basemap()
        _draw_basemap(
            self._layout.map_axis,
            basemap_array,
            prepared.utm_bbox,
            self._layout.data_crs,
            config.basemap_opacity,
        )
        _draw_attribution(
            self._layout.map_axis,
            _resolve_attribution(config, is_fetched),
        )
        self._mappable = _add_colourbar(
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

    def _load_basemap(self) -> tuple[Any, bool]:
        """``(array, is_fetched)``: custom ``background_image``, else an ESRI tile.

        ``is_fetched`` says whether the array came from ESRI, and so whether a
        style credit is owed — a custom image carries its own attribution (or
        none), which is the Consumer's business, not ours.
        """
        from . import basemap as basemap_module

        config = self._config
        prepared = self._prepared
        if config.background_image is not None:
            import numpy as _np
            from PIL import Image

            return (
                _np.asarray(Image.open(config.background_image).convert("RGB")),
                False,
            )
        array = basemap_module.load_basemap(
            prepared.utm_bbox,
            prepared.epsg,
            prepared.figsize,
            config.dpi,
            style=config.basemap_style,
            cache_dir=config.cache_dir,
            require_basemap=config.require_basemap,
        )
        return array, array is not None


def _utm_crs(epsg: int):
    """``ccrs.UTM`` for a full UTM ``epsg`` (32600+zone N, 32700+zone S)."""
    import cartopy.crs as ccrs

    southern = epsg >= 32700
    zone = epsg - (32700 if southern else 32600)
    return ccrs.UTM(zone=zone, southern_hemisphere=southern)


def _crs_from_name(name: str | None):
    """Resolve a ``RenderConfig.projection`` name to a cartopy CRS.

    ``None`` (and ``"utm"``) return ``None`` — the axis then defaults to the UTM
    data CRS. Other names select a non-UTM axis projection, e.g. to match a real
    map backdrop. Unknown names raise ``ValueError`` rather than silently falling
    back. Lazy-imports cartopy (ADR-0002).
    """
    if name is None:
        return None
    import cartopy.crs as ccrs

    named = {
        "utm": None,  # sentinel: use the UTM data CRS
        "platecarree": ccrs.PlateCarree,
        "mercator": ccrs.Mercator,
    }
    key = name.strip().lower()
    if key not in named:
        raise ValueError(
            f"Unknown projection {name!r}; expected one of {sorted(named)} "
            "(None also means UTM)."
        )
    factory = named[key]
    return None if factory is None else factory()


# Figure furniture around the map, in inches. ``figsize`` is the *map area*, so
# the figure is grown by exactly these — no percentage margins, which would both
# waste space and letterbox the aspect-locked map inside its own axes box.
_MARGIN_INCHES = 0.06  # blank border; the map has no ticks to leave room for
_TITLE_INCHES = 0.34  # extra top space, only when a suptitle is drawn
_COLOURBAR_GAP_INCHES = 0.10  # map edge -> bar
_COLOURBAR_WIDTH_INCHES = 0.18
_COLOURBAR_LABEL_INCHES = 0.75  # tick labels + axis label, right of the bar


def _create_layout(
    figsize: tuple[float, float],
    dpi: int,
    utm_bbox: dict[str, float],
    epsg: int,
    *,
    projection: Any = None,
    title: str | None = None,
) -> _Layout:
    """Build the figure, map ``GeoAxes``, colourbar axis and date-text artist.

    ``figsize`` sizes the *map area*; the figure is that plus the furniture
    constants above (margin, colourbar strip, optional title band), and the axes
    are placed absolutely. So the map keeps the bbox aspect exactly — nothing is
    lost to letterboxing — and the border stays a fixed thin rim rather than
    matplotlib's default ~12% subplot margins.

    ``epsg`` fixes the data CRS (UTM metres). ``projection`` is the axis CRS: it
    defaults to that same UTM CRS (plain UTM plot), but pass a different cartopy
    CRS to render onto a non-UTM backdrop's projection. The map extent is set to
    ``utm_bbox`` in the data CRS; a date-text artist sits at the lower-left in
    axis coordinates for the frame loop to rewrite. ``title`` becomes the figure
    suptitle when given.
    """
    from matplotlib.figure import Figure

    data_crs = _utm_crs(epsg)
    axis_projection = projection if projection is not None else data_crs

    map_width, map_height = figsize
    colourbar_strip = (
        _COLOURBAR_GAP_INCHES + _COLOURBAR_WIDTH_INCHES + _COLOURBAR_LABEL_INCHES
    )
    title_band = _TITLE_INCHES if title is not None else 0.0
    figure_width = 2 * _MARGIN_INCHES + map_width + colourbar_strip
    figure_height = 2 * _MARGIN_INCHES + map_height + title_band

    figure = Figure(figsize=(figure_width, figure_height), dpi=dpi)
    map_axis = figure.add_axes(
        (
            _MARGIN_INCHES / figure_width,
            _MARGIN_INCHES / figure_height,
            map_width / figure_width,
            map_height / figure_height,
        ),
        projection=axis_projection,
    )
    colourbar_axis = figure.add_axes(
        (
            (_MARGIN_INCHES + map_width + _COLOURBAR_GAP_INCHES) / figure_width,
            _MARGIN_INCHES / figure_height,
            _COLOURBAR_WIDTH_INCHES / figure_width,
            map_height / figure_height,
        )
    )

    map_axis.set_extent(
        (
            utm_bbox["west"],
            utm_bbox["east"],
            utm_bbox["south"],
            utm_bbox["north"],
        ),
        crs=data_crs,
    )

    if title is not None:
        figure.suptitle(title)

    date_text = map_axis.text(
        0.02,
        0.02,
        "",
        transform=map_axis.transAxes,
        ha="left",
        va="bottom",
    )
    return _Layout(figure, map_axis, colourbar_axis, date_text, data_crs)


def _draw_basemap(
    map_axis: Any,
    basemap_array: Any,
    utm_bbox: dict[str, float],
    data_crs: Any,
    opacity: float = 1.0,
) -> None:
    """Draw the basemap beneath the heatmap; no-op if ``None``.

    The array is the ESRI tile in UTM metres (row 0 = north), so it is drawn
    with ``transform=data_crs``, ``origin='upper'`` and the UTM extent; cartopy
    reprojects it if the axis CRS differs. Sits at ``zorder`` 0, under the
    heatmap. ``opacity`` below 1 fades a busy detailed style toward the figure
    background so its roads and labels stop competing with the low-alpha end of
    the ramp.
    """
    if basemap_array is None:
        return
    extent = (
        utm_bbox["west"],
        utm_bbox["east"],
        utm_bbox["south"],
        utm_bbox["north"],
    )
    map_axis.imshow(
        basemap_array,
        extent=extent,
        origin="upper",
        transform=data_crs,
        alpha=opacity,
        zorder=0,
    )


def _resolve_attribution(config: RenderConfig, is_fetched: bool) -> str:
    """The credit line to stamp: config override, else the style's, else none.

    ``config.attribution`` wins whenever it is set — including ``""``, which
    suppresses the line for a figure credited in its document caption. So ``None``
    and ``""`` must stay distinguishable; no falsy test here. With no override, a
    *fetched* basemap owes its style's credit and anything else owes nothing.
    """
    if config.attribution is not None:
        return config.attribution
    if not is_fetched:
        return ""
    from .basemap import resolve_style

    return resolve_style(config.basemap_style).attribution


_ATTRIBUTION_FONTSIZE = 4


def _draw_attribution(map_axis: Any, credit: str) -> None:
    """Stamp the basemap's credit line in the map's bottom-right; no-op if empty.

    Small, muted and above the heatmap (``zorder`` 3) so it stays legible over
    hot cells. Licence obligation, not decoration — see :data:`BASEMAP_STYLES`.

    ESRI's credit lines run to ~200 characters, wider than the map, so the text
    is wrapped to the axis. ``Text(wrap=True)`` is no use here: it wraps to the
    *figure*, which lets the line run out over the margin and the colourbar.
    """
    if not credit:
        return
    map_axis.text(
        0.99,
        0.01,
        _wrap_to_axis(map_axis, credit),
        transform=map_axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=_ATTRIBUTION_FONTSIZE,
        color="black",
        alpha=0.6,
        zorder=3,
    )


def _wrap_to_axis(map_axis: Any, text: str) -> str:
    """``text`` hard-wrapped to roughly the axis width, as newline-joined lines.

    The character budget is estimated from the axis width in points and a mean
    glyph width of ~0.6 em (measured ~0.53 on these credit lines, rounded up for
    margin) — good enough for a credit line, and it needs no renderer, which the
    figure does not yet have at scene-build time.
    """
    import textwrap

    figure = map_axis.get_figure()
    axis_width_points = (
        map_axis.get_position().width * figure.get_figwidth() * 72.0
    )
    characters_per_line = max(20, int(axis_width_points / (_ATTRIBUTION_FONTSIZE * 0.6)))
    return "\n".join(textwrap.wrap(text, characters_per_line))


def _add_colourbar(
    figure: Any,
    colourbar_axis: Any,
    cmap: Any,
    vmin: float,
    vmax: float,
    *,
    label: str,
) -> Any:
    """Attach a fixed colourbar spanning the global ``[vmin, vmax]`` scale.

    Returns the ``ScalarMappable`` so the caller reuses its norm + cmap when
    drawing each frame's heatmap, keeping frame colours consistent with the bar.
    """
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize

    mappable = ScalarMappable(norm=Normalize(vmin=vmin, vmax=vmax), cmap=cmap)
    figure.colorbar(mappable, cax=colourbar_axis, label=label)
    return mappable
