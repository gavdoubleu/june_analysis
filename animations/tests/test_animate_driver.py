"""Driver-level behaviour: CLI parsing, input-path resolution, clean error
surfacing, and the map-only geo-sentinel fallback. Config *schema* (blocks,
interpolation, unknown-key rejection) is covered in `test_animator_config.py`;
the ordering-sensitive engine composition in `test_build_pipeline.py`.
"""

import pytest


def _write_events(path):
    """Minimal Events file with two event types, for event_type validation."""
    import h5py
    import numpy as np

    with h5py.File(path, "w") as fh:
        rows = np.array([(1, 0.1)], dtype=[("person_id", "<i4"), ("time", "<f8")])
        fh.create_dataset("events/infections", data=rows)
        fh.create_dataset("events/deaths", data=rows)
    return str(path)


def test_cli_defaults_config_to_config_default(tmp_path):
    from ..animate_epidemic_example import parse_args

    args = parse_args([])
    assert args.config.name == "config_default.yaml"
    # resolved relative to the driver's configs/ dir, not the caller's cwd
    assert args.config.parent.name == "configs"


def test_missing_world_gives_clean_error_not_traceback(tmp_path):
    import yaml

    from ..animate_epidemic_example import main

    events_path = _write_events(tmp_path / "e.h5")
    config_file = tmp_path / "c.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "inputs": {"events": events_path, "world": str(tmp_path / "nope.h5")},
                "aggregate": {"event_type": "infections"},
                "output": {"root": str(tmp_path / "out")},
            }
        )
    )
    with pytest.raises(SystemExit, match="World file"):
        main(["--config", str(config_file)])


def test_missing_input_path_names_the_key():
    from ..animate_epidemic_example import resolve_input_path

    with pytest.raises(ValueError, match="inputs.world"):
        resolve_input_path(None, "world")


def test_unedited_template_placeholder_says_so():
    from ..animate_epidemic_example import resolve_input_path

    # The shipped config_default.yaml is a template; the likeliest first failure
    # is running it unedited, so the error must point at the config, not h5py.
    with pytest.raises(FileNotFoundError, match="placeholder"):
        resolve_input_path("/path/to/your/run/simulation_events.h5", "events")


def test_existing_input_path_is_returned(tmp_path):
    from ..animate_epidemic_example import resolve_input_path

    events = tmp_path / "simulation_events.h5"
    events.touch()
    assert resolve_input_path(str(events), "events") == str(events)


def test_shipped_default_config_is_path_free_and_parses():
    """The no---config fallback must not encode any developer's home directory."""
    from pathlib import Path

    from ..animate_epidemic_example import _DEFAULT_CONFIG
    from ..animator_config import load_animator_config

    config = load_animator_config(_DEFAULT_CONFIG)  # every ${key} must resolve
    assert "/home/" not in Path(_DEFAULT_CONFIG).read_text()
    assert config.inputs.events.startswith("/path/to/")
    assert not Path(config.output.root).is_absolute()


def _write_events_with_seed_venue(path):
    """infections where venue 10 has geo_unit_id -1 (seed/foreign 'no geography');
    person 1 resides in geo 5. venue 11 -> geo 200 stays put."""
    import h5py
    import numpy as np

    with h5py.File(path, "w") as fh:
        infections = np.array(
            [(1, 10, 0.1), (2, 11, 0.2)],
            dtype=[("person_id", "<i4"), ("venue_id", "<i4"), ("time", "<f8")],
        )
        fh.create_dataset("events/infections", data=infections)
        fh.create_dataset(
            "lookups/venues",
            data=np.array([(10, -1), (11, 200)],
                          dtype=[("venue_id", "<i4"), ("geo_unit_id", "<i4")]),
        )
        fh.create_dataset(
            "lookups/people",
            data=np.array([(1, 5), (2, 6)],
                          dtype=[("person_id", "<i4"), ("geo_unit_id", "<i4")]),
        )
    return str(path)


def test_map_located_falls_back_from_seed_venue_to_person_geo(tmp_path):
    import numpy as np

    from core.load_data.simulation_events import SimulationEvents

    from ..build_pipeline import located_events_for_map

    events = SimulationEvents(_write_events_with_seed_venue(tmp_path / "e.h5"))
    located = located_events_for_map(events, "infections")
    # venue 10 -> -1 -> person 1 -> 5 ; venue 11 -> 200 (unchanged).
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [5.0, 200.0])


def test_person_priority_attributes_event_to_residence_not_venue(tmp_path):
    # person 2 lives in geo 6 but was infected at venue 11 in geo 200: under
    # person priority the event counts against 6, the unit whose population the
    # rate divides by.
    import numpy as np

    from core.load_data.simulation_events import SimulationEvents

    from ..build_pipeline import located_events_for_map

    events = SimulationEvents(_write_events_with_seed_venue(tmp_path / "e.h5"))
    located = located_events_for_map(events, "infections", ("person",))
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [5.0, 6.0])


def test_map_located_drops_geo_still_unplaceable(tmp_path):
    # -1 venue with no person source at all -> stays unresolved as NaN (aggregate
    # drops it), never a literal -1 the map cannot place.
    import h5py
    import numpy as np

    from core.load_data.simulation_events import SimulationEvents

    from ..build_pipeline import located_events_for_map

    path = tmp_path / "e.h5"
    with h5py.File(path, "w") as fh:
        fh.create_dataset(
            "events/infections",
            data=np.array([(10, 0.1)], dtype=[("venue_id", "<i4"), ("time", "<f8")]),
        )
        fh.create_dataset(
            "lookups/venues",
            data=np.array([(10, -1)], dtype=[("venue_id", "<i4"), ("geo_unit_id", "<i4")]),
        )
    located = located_events_for_map(SimulationEvents(str(path)), "infections")
    assert np.isnan(located["geo_unit_id"].to_numpy()).all()


def test_missing_event_type_errors_listing_available(tmp_path):
    from core.load_data.simulation_events import SimulationEvents

    from ..build_pipeline import resolve_event_type

    events = SimulationEvents(_write_events(tmp_path / "e.h5"))
    with pytest.raises(ValueError, match=r"event_type.*infections.*deaths|deaths.*infections"):
        resolve_event_type(events, None)


def test_present_event_type_is_returned(tmp_path):
    from core.load_data.simulation_events import SimulationEvents

    from ..build_pipeline import resolve_event_type

    events = SimulationEvents(_write_events(tmp_path / "e.h5"))
    assert resolve_event_type(events, "infections") == "infections"


def test_unknown_event_type_errors_listing_available(tmp_path):
    from core.load_data.simulation_events import SimulationEvents

    from ..build_pipeline import resolve_event_type

    events = SimulationEvents(_write_events(tmp_path / "e.h5"))
    with pytest.raises(ValueError, match="infections"):
        resolve_event_type(events, "typo")
