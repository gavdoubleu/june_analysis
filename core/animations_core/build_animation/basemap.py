"""Fetch + cache the basemap a heatmap sits on, in a chosen style (ADR-0007).

The tile is requested from ESRI ArcGIS Online (no API key) *directly in the target
UTM projection*: the bounding box is passed in UTM metres with
``bboxSR = imageSR = <epsg>``, so the returned image already fills ``utm_bbox``
exactly — no reprojection or meridian-convergence crop needed, and ``utm_bbox``
doubles as the ``imshow`` extent downstream.

Which background is drawn is the **Basemap style**: shaded relief (the default,
era-neutral) or a detailed street/topo/imagery map for runs where roads and town
names help the viewer place the heat. :data:`BASEMAP_STYLES` maps each style name
to its MapServer service *and* the credit line the Frame must display — the two
travel together so a detailed tile cannot be drawn uncredited.

Fetches are expensive and identical across re-renders, so each is cached on disk
keyed by ``hash(bbox, zone, resolution, style)`` (:func:`basemap_cache_key`);
tests and repeat runs load the ``.npy`` instead of hitting the network. A failed
*network/HTTP* fetch (offline, ESRI error response) degrades to ``None`` — the
caller renders a blank background — unless ``require_basemap`` turns that into
a hard error. Any other failure (malformed input, a bad decode) always raises.

``requests`` and Pillow are lazy-imported inside :func:`_fetch_esri_tile`, so the
module stays render-free (ADR-0002).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_ESRI_EXPORT_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/{service}/MapServer/export"
)


@dataclass(frozen=True)
class BasemapStyle:
    """One selectable background: its ESRI service and its required credit.

    ``attribution`` is each service's own ``copyrightText``, verbatim. It is long
    by design — a Consumer wanting a terser line (or none, when the surrounding
    document credits sources) overrides it via ``RenderConfig.attribution``.
    """

    service: str
    attribution: str


BASEMAP_STYLES: dict[str, BasemapStyle] = {
    "shaded_relief": BasemapStyle(
        "World_Shaded_Relief",
        "Copyright:(c) 2014 Esri",
    ),
    "street": BasemapStyle(
        "World_Street_Map",
        "Sources: Esri, HERE, Garmin, USGS, Intermap, INCREMENT P, NRCan, Esri "
        "Japan, METI, Esri China (Hong Kong), Esri Korea, Esri (Thailand), NGCC, "
        "(c) OpenStreetMap contributors, and the GIS User Community",
    ),
    "topo": BasemapStyle(
        "World_Topo_Map",
        "Sources: Esri, HERE, Garmin, Intermap, increment P Corp., GEBCO, USGS, "
        "FAO, NPS, NRCAN, GeoBase, IGN, Kadaster NL, Ordnance Survey, Esri Japan, "
        "METI, Esri China (Hong Kong), (c) OpenStreetMap contributors, and the GIS "
        "User Community",
    ),
    "imagery": BasemapStyle(
        "World_Imagery",
        "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community",
    ),
}

DEFAULT_BASEMAP_STYLE = "shaded_relief"


def resolve_style(style: str) -> BasemapStyle:
    """The :class:`BasemapStyle` named ``style``; ``ValueError`` if unknown."""
    try:
        return BASEMAP_STYLES[style]
    except KeyError:
        raise ValueError(
            f"unknown basemap_style {style!r}; expected one of "
            f"{list(BASEMAP_STYLES)}"
        ) from None


def basemap_cache_key(
    utm_bbox: dict[str, float],
    epsg: int,
    resolution: tuple[int, int],
    style: str = DEFAULT_BASEMAP_STYLE,
) -> str:
    """Stable content hash of the request, for the on-disk cache filename.

    Bounds are rounded to the metre before hashing so floating-point jitter in
    the bbox does not defeat the cache. Distinct zone (``epsg``), pixel
    ``resolution`` or ``style`` yield distinct keys, so styles cannot collide in
    the cache.
    """
    canonical = "|".join(
        (
            f"{round(utm_bbox['west'])}",
            f"{round(utm_bbox['east'])}",
            f"{round(utm_bbox['south'])}",
            f"{round(utm_bbox['north'])}",
            f"{epsg}",
            f"{resolution[0]}x{resolution[1]}",
            style,
        )
    )
    return hashlib.sha1(canonical.encode()).hexdigest()


def _tile_resolution(
    figsize: tuple[float, float], dpi: int, oversample: float
) -> tuple[int, int]:
    """Requested tile size in pixels, ``oversample`` times the figure pixels."""
    width_px = max(1, int(figsize[0] * dpi * oversample))
    height_px = max(1, int(figsize[1] * dpi * oversample))
    return width_px, height_px


def _fetch_esri_tile(
    utm_bbox: dict[str, float],
    epsg: int,
    resolution: tuple[int, int],
    style: str = DEFAULT_BASEMAP_STYLE,
) -> np.ndarray:
    """Download ``style``'s tile as an RGB ``uint8`` array (no API key).

    The bbox is sent in UTM metres with ``bboxSR = imageSR = epsg`` so the image
    is returned already projected to ``utm_bbox``. Lazy-imports ``requests`` and
    Pillow (ADR-0002).
    """
    import io

    import requests
    from PIL import Image

    west, east = utm_bbox["west"], utm_bbox["east"]
    south, north = utm_bbox["south"], utm_bbox["north"]
    url = (
        f"{_ESRI_EXPORT_URL.format(service=resolve_style(style).service)}"
        f"?bbox={west},{south},{east},{north}"
        f"&bboxSR={epsg}&imageSR={epsg}"
        f"&size={resolution[0]},{resolution[1]}"
        "&format=png32&transparent=false&f=image"
    )
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    return np.asarray(image)


def load_basemap(
    utm_bbox: dict[str, float],
    epsg: int,
    figsize: tuple[float, float],
    dpi: int,
    *,
    style: str = DEFAULT_BASEMAP_STYLE,
    oversample: float = 2.0,
    cache_dir: str | None = None,
    require_basemap: bool = False,
) -> np.ndarray | None:
    """RGB basemap array for ``utm_bbox``, from cache or ESRI; ``None`` if blank.

    ``style`` selects which background is drawn (see :data:`BASEMAP_STYLES`); an
    unknown name raises ``ValueError`` rather than fetching.

    Served from ``cache_dir`` when a matching tile is on disk; otherwise fetched
    and (if ``cache_dir`` is set) cached. A network/HTTP fetch failure returns
    ``None`` so the render falls back to a blank background — unless
    ``require_basemap`` re-raises the error instead. Any other failure (malformed
    input, a bad decode) always raises, since it signals a real bug rather than
    an offline condition.
    """
    import requests

    resolve_style(style)  # fail on a bad name before any network work
    resolution = _tile_resolution(figsize, dpi, oversample)

    cache_path = None
    if cache_dir is not None:
        key = basemap_cache_key(utm_bbox, epsg, resolution, style)
        cache_path = os.path.join(cache_dir, f"basemap_{key}.npy")
        if os.path.exists(cache_path):
            return np.load(cache_path)

    try:
        tile = _fetch_esri_tile(utm_bbox, epsg, resolution, style)
    except requests.exceptions.RequestException as exc:
        if require_basemap:
            raise
        logger.warning("basemap fetch failed (%s); rendering blank background", exc)
        return None

    if cache_path is not None:
        os.makedirs(cache_dir, exist_ok=True)
        np.save(cache_path, tile)
    return tile
