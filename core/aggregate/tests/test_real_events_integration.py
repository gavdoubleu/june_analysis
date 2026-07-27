"""End-to-end on the real vendored fixture: load the *Located event table* ->
aggregate -> epidemic curve, events-only (no world_state.h5). Mirrors the
notebook path (`SimulationEvents.geo_events` -> `aggregate_events`)."""

from core.load_data import load_geo_events

from ..aggregate import aggregate_events
from ..tidy import epidemic_curve
from .conftest import REAL_EVENTS_FIXTURE, requires_real_events_fixture


@requires_real_events_fixture
def test_infections_epidemic_curve_from_real_fixture():
    located = load_geo_events(REAL_EVENTS_FIXTURE, "events/infections")
    assert located is not None and len(located) > 0

    aggregate = aggregate_events(located, event_type="infections", days_per_bin=1.0)
    curve = epidemic_curve(aggregate)

    # Every infection with a resolvable geo unit lands in exactly one bin.
    resolvable = int(located["geo_unit_id"].notna().sum())
    assert int(curve["count"].sum()) == resolvable
    assert resolvable > 0
    assert (curve["count"] >= 0).all()
    assert len(aggregate.geo_unit_ids) > 0
