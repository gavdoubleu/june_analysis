"""Fetch + cache a shaded-relief basemap for the heatmap to sit on (ADR-0007).

The tile is requested from ESRI ArcGIS Online (World_Shaded_Relief, no API key)
*directly in the target UTM projection*: the bounding box is passed in UTM metres
with ``bboxSR = imageSR = <epsg>``, so the returned image already fills
``utm_bbox`` exactly — no reprojection or meridian-convergence crop needed, and
``utm_bbox`` doubles as the ``imshow`` extent downstream.

Fetches are expensive and identical across re-renders, so each is cached on disk
keyed by ``hash(bbox, zone, resolution)`` (:func:`basemap_cache_key`); tests and
repeat runs load the ``.npy`` instead of hitting the network. A failed fetch
(offline, HTTP error) degrades to ``None`` — the caller renders a blank
background — unless ``require_basemap`` turns that into a hard error.

``requests`` and Pillow are lazy-imported inside :func:`_fetch_esri_tile`, so the
module stays render-free (ADR-0002).
"""

from __future__ import annotations

import hashlib
import os

import numpy as np

_ESRI_EXPORT_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Shaded_Relief/MapServer/export"
)


def basemap_cache_key(
    utm_bbox: dict[str, float],
    epsg: int,
    resolution: tuple[int, int],
) -> str:
    """Stable content hash of the request, for the on-disk cache filename.

    Bounds are rounded to the metre before hashing so floating-point jitter in
    the bbox does not defeat the cache. Distinct zone (``epsg``) or pixel
    ``resolution`` yield distinct keys.
    """
    canonical = "|".join(
        (
            f"{round(utm_bbox['west'])}",
            f"{round(utm_bbox['east'])}",
            f"{round(utm_bbox['south'])}",
            f"{round(utm_bbox['north'])}",
            f"{epsg}",
            f"{resolution[0]}x{resolution[1]}",
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
) -> np.ndarray:
    """Download the shaded-relief tile as an RGB ``uint8`` array (no API key).

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
        f"{_ESRI_EXPORT_URL}"
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
    oversample: float = 2.0,
    cache_dir: str | None = None,
    require_basemap: bool = False,
) -> np.ndarray | None:
    """RGB basemap array for ``utm_bbox``, from cache or ESRI; ``None`` if blank.

    Served from ``cache_dir`` when a matching tile is on disk; otherwise fetched
    and (if ``cache_dir`` is set) cached. A fetch failure returns ``None`` so the
    render falls back to a blank background — unless ``require_basemap`` re-raises
    the error instead.
    """
    resolution = _tile_resolution(figsize, dpi, oversample)

    cache_path = None
    if cache_dir is not None:
        key = basemap_cache_key(utm_bbox, epsg, resolution)
        cache_path = os.path.join(cache_dir, f"basemap_{key}.npy")
        if os.path.exists(cache_path):
            return np.load(cache_path)

    try:
        tile = _fetch_esri_tile(utm_bbox, epsg, resolution)
    except Exception:
        if require_basemap:
            raise
        return None

    if cache_path is not None:
        os.makedirs(cache_dir, exist_ok=True)
        np.save(cache_path, tile)
    return tile
