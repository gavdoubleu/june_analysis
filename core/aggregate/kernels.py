"""Dense bin x geo count kernels.

Two independent implementations of the same reduction:
  - a vectorised numpy path (always available), and
  - an optional numba scalar-loop path (lazily compiled), adapted from MAY's
    `event_aggregator` count kernels.

`numba` is an optional JIT speed-up only. Importing this module — and hence
`core.aggregate` — never requires it (ADR-0002 keeps heavy optional deps out of
the import path). The numpy and numba paths must produce identical results.
"""

from __future__ import annotations

import numpy as np

# Lazily-built cache for the compiled numba kernel; None until first use, False
# once we know numba is unavailable.
_numba_kernel = None


def numba_available() -> bool:
    try:
        import numba  # noqa: F401
    except ImportError:
        return False
    return True


def _get_numba_kernel():
    """Compile (once) and return the numba count kernel, or None if unavailable."""
    global _numba_kernel
    if _numba_kernel is not None:
        return _numba_kernel or None
    try:
        from numba import njit
    except ImportError:
        _numba_kernel = False
        return None

    @njit(cache=True)
    def _count(bin_indices, geo_indices, n_bins, n_geo):
        counts = np.zeros((n_bins, n_geo), dtype=np.int64)
        for row in range(bin_indices.shape[0]):
            counts[bin_indices[row], geo_indices[row]] += 1
        return counts

    _numba_kernel = _count
    return _count


def _count_numpy(bin_indices, geo_indices, n_bins, n_geo):
    """Vectorised dense count via flattened bincount."""
    flat = bin_indices.astype(np.int64) * n_geo + geo_indices.astype(np.int64)
    counts = np.bincount(flat, minlength=n_bins * n_geo)
    return counts.reshape(n_bins, n_geo).astype(np.int64)


def count_dense(bin_indices, geo_indices, n_bins, n_geo, use_numba=None):
    """Count events into a dense ``(n_bins, n_geo)`` int array.

    ``bin_indices`` and ``geo_indices`` are aligned 0-based index arrays.
    ``use_numba``: None auto-selects numba when installed; False forces numpy;
    True forces numba (falling back to numpy if unavailable).
    """
    bin_indices = np.ascontiguousarray(bin_indices, dtype=np.int64)
    geo_indices = np.ascontiguousarray(geo_indices, dtype=np.int64)

    if use_numba is False:
        return _count_numpy(bin_indices, geo_indices, n_bins, n_geo)

    kernel = _get_numba_kernel()
    if kernel is None:
        return _count_numpy(bin_indices, geo_indices, n_bins, n_geo)
    return kernel(bin_indices, geo_indices, n_bins, n_geo)
