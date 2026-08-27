"""End-to-end proof of `build_pipeline`'s ordering constraints — not that the
calls happen in some order, but that the *output* is what a correct order
produces (a reordering would silently corrupt one of these, per the mission
that motivated this module)."""

import h5py
import numpy as np
import pytest

from core.load_data.simulation_events import SimulationEvents

from ..build_pipeline import build_pipeline
from .conftest import REAL_EVENTS_FIXTURE, requires_real_events_fixture


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


def test_rate_per_100k_uses_resident_attribution_not_venue(tmp_path, world_fixture_path):
    # render_config_from must run before resolve_geo_priority: rate_per_100k
    # needs person attribution, or three visitors to one low-population venue
    # read as an impossible rate on the venue's own tiny geo unit (see
    # default_geo_priority's docstring: "119 infections per resident", observed).
    events = SimulationEvents(_write_events_venue_vs_person(tmp_path / "e.h5"))
    outputs = build_pipeline(
        events,
        aggregate_block={"event_type": "infections"},
        render_block={"metric": "rate_per_100k"},
        world_path=str(world_fixture_path),
    )

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
    outputs = build_pipeline(
        events,
        aggregate_block={
            "event_type": "infections",
            "time_start": 15.0,
            "days_per_frame": 1.0,
            "window_days": 5.0,
        },
        render_block=None,
        world_path=str(world_fixture_path),
    )

    assert outputs.aggregate.bin_starts[0] == pytest.approx(15.0)
