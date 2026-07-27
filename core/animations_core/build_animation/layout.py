"""Static figure scaffold for the animation (ADR-0007).

Builds the parts that are constant across every frame: a cartopy ``GeoAxes`` map
axis, a thin colourbar axis carrying the fixed global scale (ADR-0006), an
optional title, and a date-text artist that the frame loop rewrites each frame.

The map axis is a ``GeoAxes`` (not a plain ``Axes``) so its *projection is
pluggable*. The heatmap data is always UTM metres, so it is drawn with
``transform = data_crs`` (a ``ccrs.UTM``); the axis projection defaults to that
same UTM CRS — geographically correct and identical to a plain UTM plot — but
some animations use a real map backdrop whose native projection is not UTM.
Passing a different ``projection`` reprojects the backdrop, graticule and the
UTM-metre layers onto that CRS, which a plain Cartesian axis could not do.

The per-frame layers (basemap + heatmap) are drawn onto :attr:`Layout.map_axis`
by the caller; :func:`draw_basemap` is the one static image layer, added once.

matplotlib + cartopy are lazy-imported inside the functions (ADR-0002).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Layout:
    """The static figure scaffold shared by every frame.

    ``data_crs`` is the CRS of the UTM-metre layers (basemap, heatmap); the
    caller passes it as the ``transform`` when drawing them, so they land
    correctly whatever the axis :attr:`map_axis` projection is.
    """

    figure: Any
    map_axis: Any
    colourbar_axis: Any
    date_text: Any
    data_crs: Any
    heatmap_image: Any = None  # the per-frame layer, created on first draw


def _utm_crs(epsg: int):
    """``ccrs.UTM`` for a full UTM ``epsg`` (32600+zone N, 32700+zone S)."""
    import cartopy.crs as ccrs

    southern = epsg >= 32700
    zone = epsg - (32700 if southern else 32600)
    return ccrs.UTM(zone=zone, southern_hemisphere=southern)


def create_layout(
    figsize: tuple[float, float],
    dpi: int,
    utm_bbox: dict[str, float],
    epsg: int,
    *,
    projection: Any = None,
    title: str | None = None,
) -> Layout:
    """Build the figure, map ``GeoAxes``, colourbar axis and date-text artist.

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

    figure = Figure(figsize=figsize, dpi=dpi)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 0.04], wspace=0.02)
    map_axis = figure.add_subplot(grid[0, 0], projection=axis_projection)
    colourbar_axis = figure.add_subplot(grid[0, 1])

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
    return Layout(figure, map_axis, colourbar_axis, date_text, data_crs)


def draw_basemap(
    map_axis: Any,
    basemap_array: Any,
    utm_bbox: dict[str, float],
    data_crs: Any,
) -> None:
    """Draw the shaded-relief basemap beneath the heatmap; no-op if ``None``.

    The array is the ESRI tile in UTM metres (row 0 = north), so it is drawn
    with ``transform=data_crs``, ``origin='upper'`` and the UTM extent; cartopy
    reprojects it if the axis CRS differs. Sits at ``zorder`` 0, under the
    heatmap.
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
        zorder=0,
    )


def add_colourbar(
    figure: Any,
    colourbar_axis: Any,
    cmap: Any,
    vmin: float,
    vmax: float,
    *,
    label: str,
) -> Any:
    """Attach a fixed colourbar spanning the global ``[vmin, vmax]`` scale.

    Returns the ``ScalarMappable`` so the caller can reuse its norm + cmap when
    drawing each frame's heatmap, keeping frame colours consistent with the bar.
    """
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize

    mappable = ScalarMappable(norm=Normalize(vmin=vmin, vmax=vmax), cmap=cmap)
    figure.colorbar(mappable, cax=colourbar_axis, label=label)
    return mappable
