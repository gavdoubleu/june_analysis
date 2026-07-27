from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ..geo_events import load_geo_events
from ..june_events import load_decoded_events, load_enriched_events
from ..simulation_events import EventTypeSummary, SimulationEvents

from .conftest import REAL_EVENTS_FIXTURE as REAL_EVENTS_FILE
from .conftest import requires_real_events_fixture as requires_real_file


def _write_file(path):
    """Two populated event types (one with a registry column), one empty type,
    plus the lookups an enriched load needs."""
    with h5py.File(path, "w") as fh:
        infections = np.array(
            [(1, 10, 0.5, 0), (2, 20, 1.5, 255)],
            dtype=[
                ("person_id", "<i4"),
                ("venue_id", "<i4"),
                ("time", "<f8"),
                ("encounter_type_id", "u1"),
            ],
        )
        fh.create_dataset("events/infections", data=infections)

        deaths = np.array(
            [(1, 10, 0.5)],
            dtype=[("person_id", "<i4"), ("venue_id", "<i4"), ("time", "<f8")],
        )
        fh.create_dataset("events/deaths", data=deaths)

        # Present but empty — must appear in event_types() (count 0), and load to an
        # empty frame rather than raising or returning None.
        empty = np.array(
            [], dtype=[("person_id", "<i4"), ("venue_id", "<i4"), ("time", "<f8")]
        )
        fh.create_dataset("events/hospital_discharges", data=empty)

        people = np.array([(1, "f"), (2, "m")], dtype=[("person_id", "<i4"), ("sex", "S1")])
        fh.create_dataset("lookups/people", data=people)

        venues = np.array([(10, "school")], dtype=[("venue_id", "<i4"), ("type", "S10")])
        fh.create_dataset("lookups/venues", data=venues)

        fh.create_dataset(
            "metadata/registries/encounter_types",
            data=np.array(["social_encounters"], dtype="S30"),
        )
    return str(path)


def test_event_types_lists_all_types_incl_empty_prefix_stripped_sorted(tmp_path):
    run = SimulationEvents(_write_file(tmp_path / "events.h5"))

    assert run.event_types() == [
        EventTypeSummary("deaths", 1),
        EventTypeSummary("hospital_discharges", 0),
        EventTypeSummary("infections", 2),
    ]


def test_events_delegates_to_load_decoded_events(tmp_path):
    path = _write_file(tmp_path / "events.h5")
    run = SimulationEvents(path)

    pd.testing.assert_frame_equal(
        run.events("deaths"), load_decoded_events(path, "events/deaths")
    )


def test_events_forwards_columns(tmp_path):
    path = _write_file(tmp_path / "events.h5")
    run = SimulationEvents(path)

    frame = run.events("infections", columns=["time"])
    assert list(frame.columns) == ["time"]


def test_enriched_delegates_and_forwards_toggles(tmp_path):
    path = _write_file(tmp_path / "events.h5")
    run = SimulationEvents(path)

    pd.testing.assert_frame_equal(
        run.enriched("infections", with_venues=False),
        load_enriched_events(path, "events/infections", with_venues=False),
    )


def test_geo_events_delegates_and_forwards_priority(tmp_path):
    path = _write_file(tmp_path / "events.h5")
    run = SimulationEvents(path)

    pd.testing.assert_frame_equal(
        run.geo_events("infections", geo_priority=("person",)),
        load_geo_events(path, "events/infections", geo_priority=("person",)),
    )


def test_absent_event_type_raises_keyerror_listing_available(tmp_path):
    run = SimulationEvents(_write_file(tmp_path / "events.h5"))

    with pytest.raises(KeyError) as excinfo:
        run.events("typo")
    with pytest.raises(KeyError):
        run.geo_events("typo")

    message = str(excinfo.value)
    assert "typo" in message
    for name in ("deaths", "hospital_discharges", "infections"):
        assert name in message


def test_empty_but_present_type_returns_empty_frame(tmp_path):
    run = SimulationEvents(_write_file(tmp_path / "events.h5"))

    frame = run.events("hospital_discharges")
    assert isinstance(frame, pd.DataFrame)
    assert len(frame) == 0


def test_accepts_str_and_path_and_scans_once(tmp_path, monkeypatch):
    path = _write_file(tmp_path / "events.h5")

    import core.load_data.simulation_events as simulation_events_module

    calls = {"count": 0}
    real_inspect_file = simulation_events_module.inspect_file

    def counting_inspect_file(file_path):
        calls["count"] += 1
        return real_inspect_file(file_path)

    monkeypatch.setattr(simulation_events_module, "inspect_file", counting_inspect_file)

    run = SimulationEvents(Path(path))  # Path accepted
    run.event_types()
    run.events("deaths")  # second method, same instance
    assert calls["count"] == 1


@requires_real_file
def test_event_types_on_real_fixture_lists_known_types():
    run = SimulationEvents(REAL_EVENTS_FILE)

    names = {row.name for row in run.event_types()}
    assert {"deaths", "infections", "symptom_changes"} <= names
    assert all(row.n_rows >= 0 for row in run.event_types())
