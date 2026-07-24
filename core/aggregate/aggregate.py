"""Time-binned, per-geo-unit aggregation of enriched events (events-only path).

Keys on ``geo_unit_id`` — which enriched events already carry as
``venue_geo_unit_id`` / ``person_geo_unit_id`` (from the lookup joins) — so it
runs from a `simulation_events.h5` alone, with no coordinates and no World file
(ADR-0003). No rendering deps are imported here (ADR-0002).

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

# Geo-source name -> enriched-events column holding that source's geo unit.
_GEO_SOURCE_COLUMNS = {
    "venue": "venue_geo_unit_id",
    "person": "person_geo_unit_id",
}


@dataclass(frozen=True)
class Aggregate:
    """Dense time x geo count result.

    ``counts`` is ``(n_bins, n_geo)``; row *i* covers ``[bin_starts[i],
    bin_starts[i] + days_per_bin)``; column *j* is ``geo_unit_ids[j]``.
    """

    counts: np.ndarray
    geo_unit_ids: np.ndarray
    bin_starts: np.ndarray
    days_per_bin: float
    event_type: str

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


def _resolve_geo_unit(enriched_events: pd.DataFrame, geo_priority) -> np.ndarray:
    """Coalesce a single geo_unit_id per row following ``geo_priority``.

    Returns a float array with NaN where no source in the priority resolves a
    geo unit (those rows are dropped downstream).
    """
    resolved = pd.Series(np.nan, index=enriched_events.index, dtype="float64")
    for source in geo_priority:
        column = _GEO_SOURCE_COLUMNS.get(source)
        if column is None:
            raise ValueError(
                f"unknown geo source {source!r}; expected one of "
                f"{sorted(_GEO_SOURCE_COLUMNS)}"
            )
        if column not in enriched_events.columns:
            continue
        resolved = resolved.fillna(enriched_events[column])
    return resolved.to_numpy()


def aggregate_events(
    enriched_events: pd.DataFrame,
    *,
    event_type: str,
    days_per_bin: float = 1.0,
    time_start: float | None = None,
    time_end: float | None = None,
    geo_priority=("venue", "person"),
    use_numba=None,
) -> Aggregate:
    """Aggregate an enriched-events table into dense per-geo per-bin counts.

    Rows with no resolvable geo unit (per ``geo_priority``), or falling outside
    ``[time_start, time_end)``, are dropped.
    """
    times = enriched_events["time"].to_numpy(dtype="float64")
    geo_units = _resolve_geo_unit(enriched_events, geo_priority)

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
