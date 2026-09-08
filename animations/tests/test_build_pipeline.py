"""End-to-end proof of `build_pipeline`'s ordering constraints — not that the
calls happen in some order, but that the *output* is what a correct order
produces (a reordering would silently corrupt one of these, per the mission
that motivated `animator_config.py`)."""

import h5py
import numpy as np
import pytest

from core.animations_core import RenderConfig
from core.load_data.simulation_events import SimulationEvents

from ..animator_config import AggregateConfig
from ..build_pipeline import aggregation_time_start, build_pipeline
from .conftest import REAL_EVENTS_FIXTURE, requires_real_events_fixture


def test_trailing_window_config_reaches_back_so_frame_one_lands_on_time_start():
    # time_start means "start the animation here", not "ignore earlier events":
    # the driver aggregates from far enough back that the first *complete*
    # window ends on the configured day, so no burn-in-skipping frame is lost.
    import pandas as pd

    from core.aggregate.aggregate import aggregate_events
    from core.aggregate.trailing_window import trailing_mean

    aggregate = AggregateConfig(time_start=100.0, days_per_frame=1, window_days=7)
    assert aggregation_time_start(aggregate) == 94.0

    # One event a day from day 90 to 109, all in one geo unit.
    events = pd.DataFrame(
        {"time": np.arange(90.0, 110.0) + 0.5, "geo_unit_id": np.full(20, 5)}
    )
    located_aggregate = aggregate_events(
        events,
        event_type="infections",
        days_per_bin=1.0,
        time_start=aggregation_time_start(aggregate),
    )
    windowed = trailing_mean(located_aggregate, window_days=7.0)

    assert windowed.bin_starts[0] == 100.0
    # Days 94-100 each carried one event, so the first frame's mean is 1.
    assert windowed.counts[0, 0] == pytest.approx(1.0)


def test_aggregation_time_start_untouched_without_a_trailing_window():
    assert aggregation_time_start(AggregateConfig(time_start=100.0, days_per_frame=1)) == 100.0
    # Nothing to reach back to when the start is inferred from the first event.
    assert aggregation_time_start(AggregateConfig(window_days=7)) is None


def _write_events_venue_vs_person(path):
    """Three infections all at venue 100 (-> geo 30), each person resident in
    a different, separate geo unit. Venue attribution piles all three onto
    geo 30; person attribution spreads them across three residences."""
    with h5py.File(path, "w") as fh:
        infections = np.array(
            [(1, 100, 0.5), (2, 100, 1.5), (3, 100, 2.5)],
            dtype=[("person_id", "<i4"), ("venue_id", "<i4"), ("time", "<f8")],
        )
        fh.create_dataset("events/infections", data=infections)
        fh.create_dataset(
            "lookups/venues",
            data=np.array([(100, 30)], dtype=[("venue_id", "<i4"), ("geo_unit_id", "<i4")]),
        )
        fh.create_dataset(
            "lookups/people",
            data=np.array(
                [(1, 999), (2, 998), (3, 997)],
                dtype=[("person_id", "<i4"), ("geo_unit_id", "<i4")],
            ),
        )
    return str(path)


def test_event_type_resolved_before_locating_events(tmp_path, world_fixture_path):
    # resolve_event_type must run before located_events_for_map: an unknown
    # event_type has to fail with the clean "unknown event_type" error, not a
    # confusing failure from the located-events lookup itself.
    events = SimulationEvents(_write_events_venue_vs_person(tmp_path / "e.h5"))
    aggregate = AggregateConfig(event_type="typo", geo_priority=("person",))
    with pytest.raises(ValueError, match="unknown event_type"):
        build_pipeline(events, aggregate, RenderConfig(), str(world_fixture_path))


def test_rate_per_100k_geo_priority_from_config_uses_resident_attribution(tmp_path, world_fixture_path):
    # geo_priority is resolved at config-load time (animator_config), already
    # reflecting the rate metric's person-attribution default by the time it
    # reaches build_pipeline — proven end to end here.
    events = SimulationEvents(_write_events_venue_vs_person(tmp_path / "e.h5"))
    aggregate = AggregateConfig(event_type="infections", geo_priority=("person",))
    render = RenderConfig(metric="rate_per_100k")
    outputs = build_pipeline(events, aggregate, render, str(world_fixture_path))

    population = {30: 1, 999: 100, 998: 100, 997: 100}
    max_rate = np.nanmax(outputs.aggregate.rate_per_100k(population))
    # Correct (person) attribution: 1 infection / 100 residents * 1e5 = 1000.
    # Wrong (venue) attribution would pile all 3 onto geo 30 (pop 1): 300000.
    assert max_rate < 100_000


@requires_real_events_fixture
def test_trailing_window_lead_in_lands_on_time_start(world_fixture_path):
    # aggregation_time_start must run before aggregate_events, and trailing_mean
    # strictly after aggregate_events but before load_world, or the lead-in
    # maths breaks and the first surviving frame does not land on time_start.
    events = SimulationEvents(REAL_EVENTS_FIXTURE)
    aggregate = AggregateConfig(
        event_type="infections", time_start=15.0, days_per_frame=1.0, window_days=5.0
    )
    outputs = build_pipeline(events, aggregate, RenderConfig(), str(world_fixture_path))

    assert outputs.aggregate.bin_starts[0] == pytest.approx(15.0)
