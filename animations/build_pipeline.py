"""The ordering-sensitive core of the animator driver's engine composition.

Sequencing that used to live only in ``run()``'s body, unencapsulated and
untested: event_type resolution -> RenderConfig construction -> geo_priority
resolution -> located events -> aggregate -> trailing window -> world load.
Four ordering constraints hold across this span (see each helper's docstring);
``build_pipeline`` is the one place that gets them right and is tested doing
so. Input-path resolution, output-path assembly, and the final ``animate(...)``
call are deliberately outside this module's scope — they stay in ``run()``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from core.aggregate.aggregate import Aggregate, aggregate_events
from core.aggregate.trailing_window import trailing_mean
from core.animations_core import RenderConfig

if TYPE_CHECKING:
    from core.load_data.world.world import World

_METRICS = ("rate_per_100k", "count")
_NO_GEOGRAPHY_ID = -1  # geo_unit_id sentinel: seed / foreign-travel, no geography

_VENUE_THEN_PERSON = ("venue", "person")
_PERSON_ONLY = ("person",)


def default_geo_priority(metric: str):
    """Which **Geo source** to attribute an event to, given the map's metric.

    ``rate_per_100k`` divides by a Geo unit's *resident* population, so its
    numerator must count *residents* too — attribute by **person**. Venue
    attribution counts whoever was at the venue, so a fair or market in a
    200-person unit accumulates infections from visitors across the world and
    reports rates of thousands of percent (observed: 119 infections per
    resident). Residence attribution caps the ratio at 1.0, as it must.

    ``count`` has no denominator, and "where did transmission happen" is the
    interesting signal, so it keeps **venue**-then-person. Override either
    default with ``aggregate.geo_priority`` in the config.
    """
    return _PERSON_ONLY if metric == "rate_per_100k" else _VENUE_THEN_PERSON


def resolve_geo_priority(aggregate_block: dict, metric: str):
    """Config's ``aggregate.geo_priority``, else the metric's default.

    Accepts a single source (``person``) or a priority list
    (``[venue, person]``), coalesced in order by ``geo_events``.
    """
    requested = aggregate_block.get("geo_priority")
    if requested is None:
        return default_geo_priority(metric)
    if isinstance(requested, str):
        requested = [requested]
    unknown = [source for source in requested if source not in _VENUE_THEN_PERSON]
    if unknown:
        raise ValueError(
            f"unknown geo_priority source(s) {unknown}; expected any of "
            f"{list(_VENUE_THEN_PERSON)}"
        )
    return tuple(requested)


def aggregation_time_start(aggregate_block: dict) -> float | None:
    """The ``time_start`` to *aggregate* from, given the config's animation start.

    ``time_start`` means "start the animation here" — a burn-in skip, not a claim
    that earlier events are invalid. So with a **Trailing window** the aggregate
    reaches back ``window_days - days_per_frame`` further, and the leading
    incomplete bins that `trailing_mean` drops are exactly that lead-in: the
    first surviving Frame lands on the configured ``time_start`` with a full
    window behind it.

    Returns ``None`` unchanged — an inferred start (the first event) has nothing
    to reach back to, so those frames are simply dropped.
    """
    time_start = aggregate_block.get("time_start")
    window_days = aggregate_block.get("window_days")
    if time_start is None or window_days is None:
        return time_start
    days_per_frame = float(aggregate_block.get("days_per_frame", 1.0))
    return float(time_start) - (float(window_days) - days_per_frame)


def located_events_for_map(events, event_type, geo_priority=_VENUE_THEN_PERSON):
    """Located table for animation, with the ``-1`` geo sentinel map-resolved.

    In ``core`` a ``geo_unit_id`` of ``-1`` is *meaningful* — an infection seed
    or foreign-travel event with no home geography — so ``load_geo_events`` keeps
    it. A map cannot place ``-1``, so **for animation only** we fall back to the
    person's residence geo; any event still unplaceable becomes ``NaN`` (dropped
    by ``aggregate_events``). ``events`` is a :class:`SimulationEvents`.

    ``geo_priority`` picks the **Geo source**(s) — see :func:`default_geo_priority`.
    """
    import numpy as np

    located = events.geo_events(event_type, geo_priority=geo_priority)
    seed = located["geo_unit_id"] == _NO_GEOGRAPHY_ID
    # Person residence is the only fallback for a seed venue; pointless (and a
    # wasted load) when person is already the priority.
    if seed.any() and tuple(geo_priority) != _PERSON_ONLY:
        by_person = events.geo_events(event_type, geo_priority=_PERSON_ONLY)
        located.loc[seed, "geo_unit_id"] = by_person.loc[seed, "geo_unit_id"]
    located.loc[located["geo_unit_id"] == _NO_GEOGRAPHY_ID, "geo_unit_id"] = np.nan
    return located


def resolve_event_type(events, aggregate_block: dict) -> str:
    """The one event type to animate — required, never inferred (ADR-0008).

    geo/bbox/UTM/population are auto-detected downstream, but *which* event to
    animate is an editorial choice the config must state. Both an omitted
    ``event_type`` and one absent from the run raise a clear error listing the
    run's available types (``events`` is a :class:`SimulationEvents`).
    """
    available = [event.name for event in events.event_types()]
    requested = aggregate_block.get("event_type")
    if not requested:
        raise ValueError(
            "aggregate.event_type is required (never inferred); choose one of the "
            f"run's available types: {available}"
        )
    if requested not in available:
        raise ValueError(
            f"unknown event_type {requested!r}; available: {available}"
        )
    return requested


def render_config_from(render_block: dict | None) -> RenderConfig:
    """Build a :class:`RenderConfig` from a ``render:`` block.

    A Preset is a *partial* override: only the keys present are set, each over
    ``RenderConfig``'s own default (no file-to-file layering). An empty or absent
    block yields all defaults. ``start_date`` is coerced from an ISO string and
    ``metric`` is validated before the frozen config is built.
    """
    fields = dict(render_block or {})

    start_date = fields.get("start_date")
    if isinstance(start_date, str):
        fields["start_date"] = date.fromisoformat(start_date)

    metric = fields.get("metric")
    if metric is not None and metric not in _METRICS:
        raise ValueError(
            f"unknown metric {metric!r}; expected one of {list(_METRICS)}"
        )

    return RenderConfig(**fields)


@dataclass(frozen=True)
class PipelineOutputs:
    """What `build_pipeline` hands back to `run()`: the resolved event_type
    (needed for output-path assembly) plus the built Aggregate/World/RenderConfig."""

    event_type: str
    aggregate: Aggregate
    world: World
    render_config: RenderConfig


def build_pipeline(
    events, aggregate_block: dict, render_block: dict | None, world_path: str
) -> PipelineOutputs:
    """Compose the ordering-sensitive core, in the order that makes it correct.

    1. ``event_type`` resolved before it's used to locate events.
    2. ``render_config`` built before ``geo_priority`` is resolved — the metric
       decides which Geo source events are attributed to (a rate needs
       resident-attributed events; see :func:`default_geo_priority`).
    3. ``aggregation_time_start`` computed before ``aggregate_events`` runs, and
       ``trailing_mean`` applied strictly after ``aggregate_events`` but before
       the World is loaded — the Trailing window lead-in only works reaching
       back that far (see :func:`aggregation_time_start`).

    ``events`` is an already-open :class:`SimulationEvents`; ``world_path`` is
    an already-resolved path (``run()`` checks both input paths exist before
    either file is touched).
    """
    from core.load_data.world.world import load_world

    event_type = resolve_event_type(events, aggregate_block)

    render_config = render_config_from(render_block)
    geo_priority = resolve_geo_priority(aggregate_block, render_config.metric)
    located = located_events_for_map(events, event_type, geo_priority)

    days_per_frame = aggregate_block.get("days_per_frame", 1.0)
    window_days = aggregate_block.get("window_days")
    aggregation_start = aggregation_time_start(aggregate_block)
    if window_days is not None and aggregation_start is not None:
        logging.info(
            "trailing window: aggregating from day %g so the first frame at day "
            "%g has a full %g-day window",
            aggregation_start,
            aggregate_block["time_start"],
            window_days,
        )

    aggregate = aggregate_events(
        located,
        event_type=event_type,
        days_per_bin=days_per_frame,
        time_start=aggregation_start,
        time_end=aggregate_block.get("time_end"),
    )
    if window_days is not None:
        aggregate = trailing_mean(aggregate, float(window_days))

    world = load_world(world_path)

    return PipelineOutputs(
        event_type=event_type,
        aggregate=aggregate,
        world=world,
        render_config=render_config,
    )
