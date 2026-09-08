"""The *Rollup* rewrite of an `Aggregate` onto a coarser **Geo level**
(CONTEXT glossary).

Aggregate-to-Aggregate: each column is re-keyed to its ancestor at the requested
level and counts are summed. Coarsening is *not* resolution — resolution picks
which unit an event belongs to (venue vs person) and needs the Events file's
lookups, while a rollup sums an already-resolved key up a hierarchy that arrives
from the **World file**. So this sits above the engine, a sibling of
`trailing_window.trailing_mean`, and `aggregate_events`'s input stays
`time, geo_unit_id` (ADR-0005).

The hierarchy crosses the seam as a plain dict, exactly as population does for
`rate_per_100k`: this module imports nothing from `core/load_data/world`
(ADR-0003) and nothing that renders (ADR-0002).
"""

from __future__ import annotations

import logging

import numpy as np

from .aggregate import Aggregate

logger = logging.getLogger(__name__)


def rollup(aggregate: Aggregate, ancestor_by_geo_unit: dict[int, int]) -> Aggregate:
    """Re-key `aggregate`'s columns to their ancestors and sum.

    `ancestor_by_geo_unit` is a ``{geo_unit_id: ancestor_geo_unit_id}`` map for
    one level, from `World.ancestor_by_geo_unit`; a unit already at that level
    maps to itself.
    """
    # A key the map omits keeps its own id: it has no ancestor at the level (the
    # -1 sentinel, an Orphan unit, an id absent from the World file, or a unit
    # already coarser than the level). Dropping it would make totals wrong, and
    # a shared bucket would merge units with nothing in common.
    rolled_ids = np.array(
        [
            ancestor_by_geo_unit.get(int(geo_unit_id), int(geo_unit_id))
            for geo_unit_id in aggregate.geo_unit_ids
        ],
        dtype="int64",
    )

    # Absence from the map, not `rolled_id == geo_unit_id`: a unit *at* the
    # requested level legitimately maps to itself and must not be warned about.
    unplaceable = [
        int(geo_unit_id)
        for geo_unit_id in aggregate.geo_unit_ids
        if int(geo_unit_id) not in ancestor_by_geo_unit
    ]
    if unplaceable:
        # Cap the logged ids: a real ragged-hierarchy mismatch can leave every
        # column unplaceable, and interpolating the whole list makes a
        # multi-megabyte single log line hostile to terminals, log
        # aggregators, notebooks.
        unplaceable_id_cap = 20
        shown = unplaceable[:unplaceable_id_cap]
        overflow = len(unplaceable) - len(shown)
        suffix = f" (+{overflow} more)" if overflow else ""
        logger.warning(
            "%d geo unit(s) have no ancestor at the requested level and keep "
            "their own column: %s%s. Wrong world_state.h5, or a geo-level "
            "mismatch between events and world?",
            len(unplaceable),
            shown,
            suffix,
        )

    # Sorted-unique output keeps the invariant `aggregate_events` establishes via
    # np.unique, so a rolled Aggregate is interchangeable with an extracted one.
    geo_unit_ids, column_indices = np.unique(rolled_ids, return_inverse=True)
    counts = np.zeros(
        (aggregate.counts.shape[0], len(geo_unit_ids)), dtype=aggregate.counts.dtype
    )
    np.add.at(counts, (slice(None), column_indices), aggregate.counts)

    return Aggregate(
        counts=counts,
        geo_unit_ids=geo_unit_ids,
        bin_starts=aggregate.bin_starts,
        days_per_bin=aggregate.days_per_bin,
        event_type=aggregate.event_type,
        window_days=aggregate.window_days,
    )
