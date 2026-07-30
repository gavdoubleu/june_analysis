"""Time-binned, per-geo-unit aggregation of located events (events-only path).

Takes a *Located event table* — ``time, geo_unit_id`` — as produced by
``core/load_data/geo_events`` (`load_geo_events` / `SimulationEvents.geo_events`).
The venue-vs-person geo resolution lives *there*, behind the extraction seam
(ADR-0005), so this module keys straight on ``geo_unit_id`` and knows nothing of
lookup column names. Runs from a `simulation_events.h5` alone, with no coordinates
and no World file (ADR-0003). No rendering deps are imported here (ADR-0002).

Produces a dense `(n_bins, n_geo)` count `Aggregate`. Turning chosen slices into
a tidy DataFrame / CSV lives in `tidy.py`, so the fast dense path is never forced
through pandas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .kernels import count_dense


@dataclass(frozen=True)
class Aggregate:
    """Dense time x geo count result.

    ``counts`` is ``(n_bins, n_geo)`` events per bin; column *j* is
    ``geo_unit_ids[j]``. ``days_per_bin`` is the **step** between bins, so row
    *i* starts at ``bin_starts[i]``.

    Coverage is a separate question from step. Straight from ``aggregate_events``
    bins are disjoint (``window_days is None``) and row *i* covers exactly
    ``[bin_starts[i], bin_starts[i] + days_per_bin)`` with integer counts. After
    a *Trailing window* (``trailing_window.trailing_mean``) ``window_days``
    records a coverage wider than the step: row *i* covers
    ``[bin_starts[i] + days_per_bin - window_days, bin_starts[i] +
    days_per_bin)``, consecutive rows overlap, and ``counts`` holds a fractional
    *mean per bin* over that window.
    """

    counts: np.ndarray
    geo_unit_ids: np.ndarray
    bin_starts: np.ndarray
    days_per_bin: float
    event_type: str
    window_days: float | None = None

    def rate_per_100k(self, population_by_geo_unit) -> np.ndarray:
        """Per-100k rates given a ``{geo_unit_id: population}`` map.

        Returns a ``(n_bins, n_geo)`` float array aligned to ``geo_unit_ids``:
        ``counts / population * 100_000``. Population comes from the World file
        via `core/load_data/world` and is passed *in* (the aggregate never
        imports that module — ADR-0003).

        A geo unit absent from the map, or with population 0, yields a NaN
        column (a per-unit gap is not the "no World file at all" case, which
        errors earlier in `load_world`); both absent and zero-population units
        are warned about so a genuine geo-level mismatch — a zero-pop unit
        carrying events included — is not silently masked.
        """
        populations = np.array(
            [population_by_geo_unit.get(int(geo_unit_id), np.nan)
             for geo_unit_id in self.geo_unit_ids],
            dtype="float64",
        )

        # Both absent-from-map (NaN) and zero-population units yield NaN rates;
        # warn on either, since a zero-pop unit that still carries events is the
        # same class of geo-level mismatch as an absent one.
        no_population = np.isnan(populations) | (populations == 0)
        missing = self.geo_unit_ids[no_population]
        if missing.size:
            logging.warning(
                "%d geo unit(s) have no (or zero) population and get NaN rates: "
                "%s. Wrong world_state.h5, or a geo-level mismatch between events "
                "and world?",
                missing.size,
                missing.tolist(),
            )

        # Zero population -> undefined rate (NaN, not inf); guard the divide.
        with np.errstate(divide="ignore", invalid="ignore"):
            rate = self.counts / populations * 100_000.0
        rate[:, populations == 0] = np.nan
        return rate


def aggregate_events(
    located_events: pd.DataFrame,
    *,
    event_type: str,
    days_per_bin: float = 1.0,
    time_start: float | None = None,
    time_end: float | None = None,
    use_numba=None,
) -> Aggregate:
    """Aggregate a *Located event table* (``time, geo_unit_id``) into dense
    per-geo per-bin counts.

    Rows with no geo unit (``NaN`` ``geo_unit_id``, from an unresolved source in
    ``load_geo_events``), or falling outside ``[time_start, time_end)``, are
    dropped.
    """
    times = located_events["time"].to_numpy(dtype="float64")
    geo_units = located_events["geo_unit_id"].to_numpy(dtype="float64")

    # Default window anchors bins to the day (bin) grid, so day-binned counts
    # align to whole days rather than to the first event's fractional time.
    if time_start is None:
        first = float(times.min()) if times.size else 0.0
        time_start = np.floor(first / days_per_bin) * days_per_bin

    keep = ~np.isnan(geo_units) & (times >= time_start)
    if time_end is not None:
        keep &= times < time_end
    times = times[keep]
    geo_units = geo_units[keep].astype(np.int64)

    if time_end is None:
        last = float(times.max()) if times.size else time_start
        n_bins = int(np.floor((last - time_start) / days_per_bin)) + 1
    else:
        n_bins = int(np.ceil((time_end - time_start) / days_per_bin))
    n_bins = max(1, n_bins)
    bin_starts = time_start + np.arange(n_bins) * days_per_bin

    geo_unit_ids, geo_indices = np.unique(geo_units, return_inverse=True)
    bin_indices = np.floor((times - time_start) / days_per_bin).astype(np.int64)
    # Clip guards floating-point round-up at the final boundary.
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)

    counts = count_dense(
        bin_indices, geo_indices, n_bins, len(geo_unit_ids), use_numba=use_numba
    )

    return Aggregate(
        counts=counts,
        geo_unit_ids=geo_unit_ids,
        bin_starts=bin_starts,
        days_per_bin=days_per_bin,
        event_type=event_type,
    )
