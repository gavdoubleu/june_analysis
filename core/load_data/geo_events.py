"""Light *Located event table* path: events with a single resolved ``geo_unit_id``.

The cheap feed for ``core/aggregate``. A *Decoded event table* carries
``person_id`` / ``venue_id`` but no geo unit; the full *Enriched event table*
does, but only by joining the **entire** people lookup (plus every
``people_properties`` column) and the whole venues lookup. This module joins
**only** ``geo_unit_id`` from those lookups and coalesces it to one column per
event (venue-then-person priority), returning just ``time, geo_unit_id``.

Owned by ``june_analysis`` (not the vendored ``june_events``) because the
venue/person priority is an analysis choice (ADR-0001 keeps vendored divergence
minimal). No render deps are imported here (ADR-0002).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .june_events import (
    PEOPLE_DATASET,
    VENUES_DATASET,
    dataset_field_names,
    enrich_with_people,
    enrich_with_venues,
    load_decoded_events,
    load_people_lookup,
    load_venues_lookup,
)

# Geo-source name -> (event id column, its prefixed geo column after the join,
# lookup dataset path the geo unit is read from).
_GEO_SOURCES = {
    "venue": ("venue_id", "venue_geo_unit_id", VENUES_DATASET),
    "person": ("person_id", "person_geo_unit_id", PEOPLE_DATASET),
}

_LOOKUP_GEO_COLUMN = "geo_unit_id"


def load_geo_events(
    path: str,
    dataset_path: str,
    *,
    geo_priority=("venue", "person"),
) -> pd.DataFrame | None:
    """Load one event type as ``time, geo_unit_id`` — the *Located event table*.

    Resolves each event's geo unit by joining **only** ``geo_unit_id`` from the
    venue/person lookups and coalescing per ``geo_priority`` (an absent source is
    skipped, not an error). Rows with no resolvable geo unit keep ``NaN`` —
    ``aggregate_events`` drops them. Returns ``None`` if the dataset is absent.
    """
    raw_fields = dataset_field_names(path, dataset_path)
    if raw_fields is None:
        return None

    # Only load the id columns this event type actually has, plus time.
    wanted_ids = [
        id_column
        for source in geo_priority
        if (id_column := _GEO_SOURCES[source][0]) in raw_fields
    ]
    events = load_decoded_events(
        path, dataset_path, columns=["time", *wanted_ids]
    )
    if events is None:
        return None

    resolved = pd.Series(np.nan, index=events.index, dtype="float64")
    for source in geo_priority:
        if source not in _GEO_SOURCES:
            raise ValueError(
                f"unknown geo source {source!r}; expected one of "
                f"{sorted(_GEO_SOURCES)}"
            )
        id_column, geo_column, lookup_dataset = _GEO_SOURCES[source]
        if id_column not in events.columns:
            continue
        # Peek then project: skip a source whose lookup lacks geo_unit_id
        # (absent source, not an error) rather than let the projected read raise.
        lookup_fields = dataset_field_names(path, lookup_dataset)
        if lookup_fields is None or _LOOKUP_GEO_COLUMN not in lookup_fields:
            continue
        projection = [id_column, _LOOKUP_GEO_COLUMN]
        if source == "venue":
            lookup = load_venues_lookup(path, columns=projection)
            joined = enrich_with_venues(events[[id_column]], lookup)
        else:
            lookup = load_people_lookup(
                path, include_properties=False, columns=projection
            )
            joined = enrich_with_people(events[[id_column]], lookup)
        resolved = resolved.fillna(joined[geo_column])

    return pd.DataFrame({"time": events["time"].to_numpy(), "geo_unit_id": resolved.to_numpy()})
