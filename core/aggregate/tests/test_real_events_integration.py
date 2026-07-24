"""End-to-end on the real vendored fixture: load enriched events -> aggregate ->
epidemic curve, events-only (no world_state.h5). Mirrors the notebook path."""

from core.load_data.june_events import load_enriched_events

from ..aggregate import aggregate_events
from ..tidy import epidemic_curve
from .conftest import REAL_EVENTS_FIXTURE, requires_real_events_fixture


@requires_real_events_fixture
def test_infections_epidemic_curve_from_real_fixture():
    events = load_enriched_events(REAL_EVENTS_FIXTURE, "events/infections")
    assert events is not None and len(events) > 0

    aggregate = aggregate_events(events, event_type="infections", days_per_bin=1.0)
    curve = epidemic_curve(aggregate)

    # 824 infections in the fixture, all resolvable to a geo unit.
    assert int(curve["count"].sum()) == len(events)
    assert (curve["count"] >= 0).all()
    assert len(aggregate.geo_unit_ids) > 0
