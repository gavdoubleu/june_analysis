"""Turn a dense `Aggregate` into tidy DataFrames for just the wanted slices.

Kept separate from the dense aggregation so the fast numba/numpy path is never
forced through pandas: a consumer materialises only the geos/curve it will plot
or export to CSV, not the whole `(n_bins, n_geo)` grid.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .aggregate import Aggregate


def epidemic_curve(aggregate: Aggregate) -> pd.DataFrame:
    """Per-bin total counts (summed over all geo units) as ``[bin_start, count]``.

    The epidemic curve — cheap, avoids building the full long frame.
    """
    totals = aggregate.counts.sum(axis=1)
    return pd.DataFrame({"bin_start": aggregate.bin_starts, "count": totals})


def to_long_dataframe(
    aggregate: Aggregate,
    *,
    geo_unit_ids=None,
    drop_zero: bool = True,
) -> pd.DataFrame:
    """Tidy ``[bin_start, geo_unit_id, event_type, count]`` for chosen geo units.

    ``geo_unit_ids`` selects a subset of columns (default all); ``drop_zero``
    omits empty cells so exports stay compact.
    """
    if geo_unit_ids is None:
        column_indices = np.arange(len(aggregate.geo_unit_ids))
    else:
        wanted = np.asarray(geo_unit_ids)
        column_indices = np.flatnonzero(np.isin(aggregate.geo_unit_ids, wanted))

    selected_counts = aggregate.counts[:, column_indices]
    selected_geo_ids = aggregate.geo_unit_ids[column_indices]

    n_bins = len(aggregate.bin_starts)
    bin_column = np.repeat(aggregate.bin_starts, len(column_indices))
    geo_column = np.tile(selected_geo_ids, n_bins)
    count_column = selected_counts.reshape(-1)

    frame = pd.DataFrame(
        {
            "bin_start": bin_column,
            "geo_unit_id": geo_column,
            "event_type": aggregate.event_type,
            "count": count_column,
        }
    )
    if drop_zero:
        frame = frame[frame["count"] > 0].reset_index(drop=True)
    return frame
