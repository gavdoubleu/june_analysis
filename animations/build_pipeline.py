"""The ordering-sensitive core of the animator driver's engine composition.

Sequencing that used to live only in ``run()``'s body, unencapsulated and
untested: event_type resolution -> located events -> aggregate -> trailing
window -> world load. Two ordering constraints hold across this span (see
each helper's docstring); ``build_pipeline`` is the one place that gets them
right and is tested doing so. Input-path resolution, output-path assembly,
config parsing/validation (see :mod:`animations.animator_config`), and the
final ``animate(...)`` call are deliberately outside this module's scope —
they stay in ``run()``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.aggregate.aggregate import Aggregate, aggregate_events
from core.aggregate.trailing_window import trailing_mean
from core.animations_core import RenderConfig

from .animator_config import AggregateConfig

if TYPE_CHECKING:
    from core.load_data.world.world import World

_NO_GEOGRAPHY_ID = -1  # geo_unit_id sentinel: seed / foreign-travel, no geography


def located_events_for_map(events, event_type, geo_priority=("venue", "person")):
    """Located table for animation, with the ``-1`` geo sentinel map-resolved.

    In ``core`` a ``geo_unit_id`` of ``-1`` is *meaningful* — an infection seed
    or foreign-travel event with no home geography — so ``load_geo_events`` keeps
    it. A map cannot place ``-1``, so **for animation only** we fall back to the
    person's residence geo; any event still unplaceable becomes ``NaN`` (dropped
    by ``aggregate_events``). ``events`` is a :class:`SimulationEvents`.

    ``geo_priority`` picks the **Geo source**(s) — see
    :func:`animations.animator_config.default_geo_priority`.
    """
    import numpy as np

    located = events.geo_events(event_type, geo_priority=geo_priority)
    seed = located["geo_unit_id"] == _NO_GEOGRAPHY_ID
    # Person residence is the only fallback for a seed venue; pointless (and a
    # wasted load) when person is already the priority.
    if seed.any() and tuple(geo_priority) != ("person",):
        by_person = events.geo_events(event_type, geo_priority=("person",))
        located.loc[seed, "geo_unit_id"] = by_person.loc[seed, "geo_unit_id"]
    located.loc[located["geo_unit_id"] == _NO_GEOGRAPHY_ID, "geo_unit_id"] = np.nan
    return located


def resolve_event_type(events, event_type: str | None) -> str:
    """The one event type to animate — required, never inferred (ADR-0008).

    geo/bbox/UTM/population are auto-detected downstream, but *which* event to
    animate is an editorial choice the config must state. Both an omitted
    ``event_type`` and one absent from the run raise a clear error listing the
    run's available types (``events`` is a :class:`SimulationEvents`).
    """
    available = [event.name for event in events.event_types()]
    if not event_type:
        raise ValueError(
            "aggregate.event_type is required (never inferred); choose one of the "
            f"run's available types: {available}"
        )
    if event_type not in available:
        raise ValueError(
            f"unknown event_type {event_type!r}; available: {available}"
        )
    return event_type


@dataclass(frozen=True)
class PipelineOutputs:
    """What `build_pipeline` hands back to `run()`: the resolved event_type
    (needed for output-path assembly) plus the built Aggregate/World/RenderConfig."""

    event_type: str
    aggregate: Aggregate
    world: World
    render_config: RenderConfig


def build_pipeline(
    events, aggregate: AggregateConfig, render: RenderConfig, world_path: str
) -> PipelineOutputs:
    """Compose the ordering-sensitive core, in the order that makes it correct.

    1. ``event_type`` resolved before it's used to locate events.
    2. ``trailing_mean`` applied strictly after ``aggregate_events`` but before
       the World is loaded — the Trailing window lead-in only works reaching
       back that far (see :func:`aggregation_time_start`).

    ``events`` is an already-open :class:`SimulationEvents`; ``world_path`` is
    an already-resolved path (``run()`` checks both input paths exist before
    either file is touched). ``aggregate``/``render`` are already-validated
    config, built by :func:`animations.animator_config.load_animator_config`
    (``geo_priority`` on ``aggregate`` is already resolved against
    ``render.metric`` at that point).
    """
    from core.load_data.world.world import load_world

    event_type = resolve_event_type(events, aggregate.event_type)
    located = located_events_for_map(events, event_type, aggregate.geo_priority)

    aggregation_start = aggregation_time_start(aggregate)
    if aggregate.window_days is not None and aggregation_start is not None:
        logging.info(
            "trailing window: aggregating from day %g so the first frame at day "
            "%g has a full %g-day window",
            aggregation_start,
            aggregate.time_start,
            aggregate.window_days,
        )

    located_aggregate = aggregate_events(
        located,
        event_type=event_type,
        days_per_bin=aggregate.days_per_frame,
        time_start=aggregation_start,
        time_end=aggregate.time_end,
    )
    if aggregate.window_days is not None:
        located_aggregate = trailing_mean(located_aggregate, aggregate.window_days)

    world = load_world(world_path)

    return PipelineOutputs(
        event_type=event_type,
        aggregate=located_aggregate,
        world=world,
        render_config=render,
    )


def aggregation_time_start(aggregate: AggregateConfig) -> float | None:
    """The ``time_start`` to *aggregate* from, given the config's animation start.

    ``time_start`` means "start the animation here" — a burn-in skip, not a claim
    that earlier events are invalid. So with a **Trailing window** the aggregate
    reaches back ``window_days - days_per_frame`` further, and the leading
    incomplete bins that `trailing_mean` drops are exactly that lead-in: the
    first surviving Frame lands on the configured ``time_start`` with a full
    window behind it.

    Returns ``time_start`` unchanged — an inferred start (the first event) has
    nothing to reach back to, so those frames are simply dropped.
    """
    if aggregate.time_start is None or aggregate.window_days is None:
        return aggregate.time_start
    return aggregate.time_start - (aggregate.window_days - aggregate.days_per_frame)
