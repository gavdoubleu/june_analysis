import h5py
import numpy as np
import pytest

from ..load_enriched import load_decoded_events


def _spy_on_load_registry(monkeypatch):
    from .. import load_enriched as load_enriched_module

    loaded = []
    original = load_enriched_module.load_registry

    def spy(path, registry_name):
        loaded.append(registry_name)
        return original(path, registry_name)

    monkeypatch.setattr(load_enriched_module, "load_registry", spy)
    return loaded


def _write_minimal_file(path):
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

        people = np.array([(1, "f"), (2, "m")], dtype=[("person_id", "<i4"), ("sex", "S1")])
        fh.create_dataset("lookups/people", data=people)

        venues = np.array([(10, "school")], dtype=[("venue_id", "<i4"), ("type", "S10")])
        fh.create_dataset("lookups/venues", data=venues)

        fh.create_dataset(
            "metadata/registries/encounter_types",
            data=np.array(["social_encounters"], dtype="S30"),
        )
    return path


def _write_infections_with_symptoms(path):
    # infections carrying BOTH registries (encounter_types + symptoms) and an
    # infector_id, so tests can probe selective decode and the no-infector mask.
    with h5py.File(path, "w") as fh:
        infections = np.array(
            [(1, -1, 10, 0.5, 255, 0), (2, 1, 20, 1.5, 0, 2)],
            dtype=[
                ("person_id", "<i4"),
                ("infector_id", "<i4"),
                ("venue_id", "<i4"),
                ("time", "<f8"),
                ("encounter_type_id", "u1"),
                ("infector_symptom_id", "<u2"),
            ],
        )
        fh.create_dataset("events/infections", data=infections)
        fh.create_dataset(
            "metadata/registries/encounter_types",
            data=np.array(["social_encounters"], dtype="S30"),
        )
        fh.create_dataset(
            "metadata/registries/symptoms",
            data=np.array(["recovered", "exposed", "infected"], dtype="S30"),
        )
    return path


def test_load_decoded_events_decodes_registries_without_joins(tmp_path):
    path = _write_minimal_file(str(tmp_path / "events.h5"))

    decoded = load_decoded_events(path, "events/infections")

    assert list(decoded["encounter_type"]) == [
        "social_encounters",
        "regular_non_coordinated_encounter",
    ]
    # raw person_id/venue_id stay; the lookup-join columns must NOT appear.
    assert "person_sex" not in decoded.columns
    assert "venue_type" not in decoded.columns


def test_passthrough_only_columns_load_no_registry(tmp_path, monkeypatch):
    path = _write_infections_with_symptoms(str(tmp_path / "events.h5"))
    loaded = _spy_on_load_registry(monkeypatch)

    decoded = load_decoded_events(path, "events/infections", columns=["time"])

    assert list(decoded.columns) == ["time"]
    assert loaded == []


def test_requesting_one_decoded_column_loads_only_its_registry(tmp_path, monkeypatch):
    path = _write_infections_with_symptoms(str(tmp_path / "events.h5"))
    loaded = _spy_on_load_registry(monkeypatch)

    decoded = load_decoded_events(path, "events/infections", columns=["infector_symptom"])

    assert loaded == ["symptoms"]
    assert "encounter_type" not in decoded.columns


def test_no_infector_mask_holds_when_infector_id_not_requested(tmp_path):
    path = _write_infections_with_symptoms(str(tmp_path / "events.h5"))

    decoded = load_decoded_events(path, "events/infections", columns=["infector_symptom"])

    # row 0 has infector_id == -1 (seed): masked -> no_infector, not a
    # fabricated "recovered" from the default-0 symptom id.
    assert list(decoded["infector_symptom"]) == ["no_infector", "infected"]


def test_requesting_decoded_column_drops_its_source_id(tmp_path):
    path = _write_infections_with_symptoms(str(tmp_path / "events.h5"))

    decoded = load_decoded_events(path, "events/infections", columns=["encounter_type"])

    assert list(decoded.columns) == ["encounter_type"]
    assert "encounter_type_id" not in decoded.columns


def test_unknown_column_name_errors_clearly(tmp_path):
    path = _write_infections_with_symptoms(str(tmp_path / "events.h5"))

    with pytest.raises(KeyError, match="nonexistent"):
        load_decoded_events(path, "events/infections", columns=["nonexistent"])


def test_missing_dataset_returns_none(tmp_path):
    path = _write_infections_with_symptoms(str(tmp_path / "events.h5"))

    assert load_decoded_events(path, "events/deaths", columns=["time"]) is None
