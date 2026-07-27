"""`load_geo_events`: the light *Located event table* path — one resolved
``geo_unit_id`` per event, venue-then-person priority, no full lookup metadata."""

import h5py
import numpy as np

from ..geo_events import load_geo_events


def _write_file(path):
    """Venue geo and person geo deliberately differ, so priority and fallback are
    both observable. venue -1 has no lookup row (its geo is unresolvable)."""
    with h5py.File(path, "w") as fh:
        infections = np.array(
            [(1, 10, 0.1), (2, -1, 0.2), (3, 11, 0.9)],
            dtype=[("person_id", "<i4"), ("venue_id", "<i4"), ("time", "<f8")],
        )
        fh.create_dataset("events/infections", data=infections)

        # No venue_id column at all — the venue source is simply absent here.
        no_venue = np.array(
            [(1, 0.3), (2, 0.4)],
            dtype=[("person_id", "<i4"), ("time", "<f8")],
        )
        fh.create_dataset("events/hospital_admissions", data=no_venue)

        venues = np.array(
            [(10, 100), (11, 200)],
            dtype=[("venue_id", "<i4"), ("geo_unit_id", "<i4")],
        )
        fh.create_dataset("lookups/venues", data=venues)

        people = np.array(
            [(1, 1), (2, 2), (3, 3)],
            dtype=[("person_id", "<i4"), ("geo_unit_id", "<i4")],
        )
        fh.create_dataset("lookups/people", data=people)

        # A people_property present to prove the geo path does NOT expand it.
        fh.create_dataset(
            "lookups/people_properties/ethnicity",
            data=np.array(["a", "b", "c"], dtype="S1"),
        )
    return str(path)


def test_returns_only_time_and_geo_unit_id(tmp_path):
    located = load_geo_events(_write_file(tmp_path / "e.h5"), "events/infections")
    assert list(located.columns) == ["time", "geo_unit_id"]
    assert len(located) == 3


def test_venue_priority_with_person_fallback(tmp_path):
    located = load_geo_events(_write_file(tmp_path / "e.h5"), "events/infections")
    # row0 venue 10 -> 100 ; row1 venue -1 unresolved -> person 2 ; row2 venue 11 -> 200.
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [100.0, 2.0, 200.0])


def test_person_priority_keys_on_residence(tmp_path):
    located = load_geo_events(
        _write_file(tmp_path / "e.h5"), "events/infections", geo_priority=("person",)
    )
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [1.0, 2.0, 3.0])


def test_source_absent_from_event_type_falls_through(tmp_path):
    # hospital_admissions has no venue_id column: venue source skipped, person used.
    located = load_geo_events(
        _write_file(tmp_path / "e.h5"), "events/hospital_admissions"
    )
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [1.0, 2.0])


def test_absent_dataset_returns_none(tmp_path):
    assert load_geo_events(_write_file(tmp_path / "e.h5"), "events/nope") is None


def test_lookup_without_geo_unit_id_skips_source_not_raises(tmp_path):
    # Malformed venue source: lookup exists but carries no geo_unit_id.
    # peek-then-project must skip the venue source (fall through to person), not
    # raise on the projected read.
    path = tmp_path / "e.h5"
    with h5py.File(path, "w") as fh:
        infections = np.array(
            [(1, 10, 0.1), (2, 11, 0.2)],
            dtype=[("person_id", "<i4"), ("venue_id", "<i4"), ("time", "<f8")],
        )
        fh.create_dataset("events/infections", data=infections)
        venues = np.array(
            [(10, b"x"), (11, b"y")],
            dtype=[("venue_id", "<i4"), ("name", "S8")],
        )
        fh.create_dataset("lookups/venues", data=venues)
        people = np.array(
            [(1, 1), (2, 2)],
            dtype=[("person_id", "<i4"), ("geo_unit_id", "<i4")],
        )
        fh.create_dataset("lookups/people", data=people)

    located = load_geo_events(str(path), "events/infections")
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [1.0, 2.0])


def test_lookup_without_id_column_skips_source_not_raises(tmp_path):
    # Malformed venue source: lookup carries geo_unit_id but not its own
    # venue_id. The projected read [venue_id, geo_unit_id] would KeyError on the
    # missing venue_id; the peek must skip the venue source (fall through to
    # person), not raise. Mirror of the missing-geo_unit_id case above.
    path = tmp_path / "e.h5"
    with h5py.File(path, "w") as fh:
        infections = np.array(
            [(1, 10, 0.1), (2, 11, 0.2)],
            dtype=[("person_id", "<i4"), ("venue_id", "<i4"), ("time", "<f8")],
        )
        fh.create_dataset("events/infections", data=infections)
        venues = np.array(
            [(100,), (200,)],
            dtype=[("geo_unit_id", "<i4")],
        )
        fh.create_dataset("lookups/venues", data=venues)
        people = np.array(
            [(1, 1), (2, 2)],
            dtype=[("person_id", "<i4"), ("geo_unit_id", "<i4")],
        )
        fh.create_dataset("lookups/people", data=people)

    located = load_geo_events(str(path), "events/infections")
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [1.0, 2.0])
