import h5py
import numpy as np
import pytest

from ..io import load_people_lookup, load_venues_lookup

from .conftest import REAL_EVENTS_FIXTURE as REAL_EVENTS_FILE
from .conftest import requires_real_events_fixture as requires_real_file


def _write_lookups(path):
    with h5py.File(path, "w") as fh:
        venues = np.array(
            [(10, b"school", b"education", 100), (11, b"home", b"residence", 200)],
            dtype=[
                ("venue_id", "<i4"),
                ("name", "S16"),
                ("type", "S16"),
                ("geo_unit_id", "<i4"),
            ],
        )
        fh.create_dataset("lookups/venues", data=venues)

        people = np.array(
            [(1, 30.0, 5), (2, 40.0, 6)],
            dtype=[("person_id", "<i4"), ("age", "<f8"), ("geo_unit_id", "<i4")],
        )
        fh.create_dataset("lookups/people", data=people)
        fh.create_dataset(
            "lookups/people_properties/ethnicity",
            data=np.array([b"a", b"b"], dtype="S1"),
        )
    return str(path)


def test_load_venues_lookup_columns_projects_to_requested_fields(tmp_path):
    venues = load_venues_lookup(
        _write_lookups(tmp_path / "e.h5"), columns=["venue_id", "geo_unit_id"]
    )
    assert list(venues.columns) == ["venue_id", "geo_unit_id"]


def test_load_venues_lookup_columns_still_decodes_byte_kind_projection(tmp_path):
    venues = load_venues_lookup(
        _write_lookups(tmp_path / "e.h5"), columns=["venue_id", "type"]
    )
    assert list(venues.columns) == ["venue_id", "type"]
    assert isinstance(venues["type"].iloc[0], str)
    assert venues["type"].iloc[0] == "education"


def test_load_people_lookup_columns_compose_with_properties(tmp_path):
    people = load_people_lookup(
        _write_lookups(tmp_path / "e.h5"),
        include_properties=True,
        columns=["person_id", "geo_unit_id"],
    )
    # Projected main columns first, then the appended property column.
    assert list(people.columns) == ["person_id", "geo_unit_id", "ethnicity"]
    assert people["ethnicity"].iloc[0] == "a"


def test_load_people_lookup_columns_without_properties_stays_narrow(tmp_path):
    people = load_people_lookup(
        _write_lookups(tmp_path / "e.h5"),
        include_properties=False,
        columns=["person_id", "geo_unit_id"],
    )
    assert list(people.columns) == ["person_id", "geo_unit_id"]


@pytest.mark.parametrize("loader", [load_venues_lookup, load_people_lookup])
def test_lookup_columns_unknown_name_raises_keyerror_listing_valid(tmp_path, loader):
    with pytest.raises(KeyError, match="nonsense"):
        loader(_write_lookups(tmp_path / "e.h5"), columns=["nonsense"])


def test_projected_lookup_read_opens_file_once_no_validation_repeek(tmp_path, monkeypatch):
    """I/O-economy guard: validation now runs inside load_raw_table's single open
    handle, so a projected read must open the file once, not twice (the old
    _validate_columns re-peek). A re-introduced separate peek pushes this to 2."""
    real_open = h5py.File
    opens = []

    def counting_open(*args, **kwargs):
        opens.append(args[0] if args else kwargs.get("name"))
        return real_open(*args, **kwargs)

    path = _write_lookups(tmp_path / "e.h5")
    monkeypatch.setattr(h5py, "File", counting_open)

    load_venues_lookup(path, columns=["venue_id", "geo_unit_id"])

    assert len(opens) == 1


@requires_real_file
def test_load_venues_lookup_decodes_byte_columns_to_str():
    venues = load_venues_lookup(REAL_EVENTS_FILE)

    assert isinstance(venues["name"].iloc[0], str)
    assert isinstance(venues["type"].iloc[0], str)


@requires_real_file
def test_load_people_lookup_decodes_byte_columns_to_str():
    people = load_people_lookup(REAL_EVENTS_FILE, include_properties=False)

    assert isinstance(people["sex"].iloc[0], str)
    assert isinstance(people["schedule_type"].iloc[0], str)


@requires_real_file
def test_load_people_lookup_merges_properties_by_position():
    people = load_people_lookup(REAL_EVENTS_FILE, include_properties=True)

    assert "ethnicity" in people.columns
    with h5py.File(REAL_EVENTS_FILE, "r") as fh:
        assert len(people) == fh["lookups/people"].shape[0]
    assert isinstance(people["ethnicity"].iloc[0], str)


def test_load_people_lookup_handles_file_missing_properties_group(tmp_path):
    path = tmp_path / "minimal_simulation_events.h5"
    dtype = [("person_id", "<i4"), ("age", "<f8")]
    with h5py.File(path, "w") as fh:
        fh.create_dataset(
            "lookups/people", data=np.array([(1, 30.0)], dtype=dtype)
        )

    people = load_people_lookup(str(path), include_properties=True)

    assert list(people.columns) == ["person_id", "age"]


def test_load_people_lookup_raises_when_property_length_mismatches_people(tmp_path):
    path = tmp_path / "minimal_simulation_events.h5"
    dtype = [("person_id", "<i4"), ("age", "<f8")]
    with h5py.File(path, "w") as fh:
        fh.create_dataset(
            "lookups/people", data=np.array([(1, 30.0), (2, 40.0)], dtype=dtype)
        )
        fh.create_dataset("lookups/people_properties/ethnicity", data=np.array(["a"], dtype="S1"))

    with pytest.raises(ValueError, match="ethnicity"):
        load_people_lookup(str(path), include_properties=True)
