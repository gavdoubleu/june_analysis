"""Driver config logic: interpolation, RenderConfig mapping, error paths.

Behaviour through the driver's public helpers — no HDF5, no render deps. The
engine composition (load -> aggregate -> world -> render) is covered by the real
plague/generality acceptance runs, not mocked here.
"""

import pytest

from ..animate_epidemic_example import render_config_from, resolve_interpolations


def test_interpolation_resolves_against_top_level_scalars():
    raw = {
        "data_root": "/data",
        "inputs": {"events": "${data_root}/events.h5"},
    }
    resolved = resolve_interpolations(raw)
    assert resolved["inputs"]["events"] == "/data/events.h5"


def test_unknown_interpolation_key_raises_clear_error():
    raw = {"data_root": "/data", "inputs": {"events": "${typo_root}/events.h5"}}
    with pytest.raises(ValueError, match=r"typo_root.*data_root"):
        resolve_interpolations(raw)


def test_render_block_overrides_only_present_keys():
    config = render_config_from({"ramp": "inferno", "fps": 15})
    assert config.ramp == "inferno"
    assert config.fps == 15
    # untouched keys keep RenderConfig defaults
    assert config.metric == "rate_per_100k"
    assert config.sigma == 2.0


def test_empty_render_block_is_all_defaults():
    from core.animations_core import RenderConfig

    assert render_config_from({}) == RenderConfig()
    assert render_config_from(None) == RenderConfig()


def test_start_date_string_is_coerced_to_date():
    from datetime import date

    config = render_config_from({"start_date": "1348-06-24"})
    assert config.start_date == date(1348, 6, 24)


def test_unknown_metric_is_rejected():
    with pytest.raises(ValueError, match="metric"):
        render_config_from({"metric": "bananas"})


def _write_events(path):
    """Minimal Events file with two event types, for event_type validation."""
    import h5py
    import numpy as np

    with h5py.File(path, "w") as fh:
        rows = np.array([(1, 0.1)], dtype=[("person_id", "<i4"), ("time", "<f8")])
        fh.create_dataset("events/infections", data=rows)
        fh.create_dataset("events/deaths", data=rows)
    return str(path)


def test_missing_event_type_errors_listing_available(tmp_path):
    from core.load_data.simulation_events import SimulationEvents

    from ..animate_epidemic_example import resolve_event_type

    events = SimulationEvents(_write_events(tmp_path / "e.h5"))
    with pytest.raises(ValueError, match=r"event_type.*infections.*deaths|deaths.*infections"):
        resolve_event_type(events, {})


def test_present_event_type_is_returned(tmp_path):
    from core.load_data.simulation_events import SimulationEvents

    from ..animate_epidemic_example import resolve_event_type

    events = SimulationEvents(_write_events(tmp_path / "e.h5"))
    assert resolve_event_type(events, {"event_type": "infections"}) == "infections"


def test_unknown_event_type_errors_listing_available(tmp_path):
    from core.load_data.simulation_events import SimulationEvents

    from ..animate_epidemic_example import resolve_event_type

    events = SimulationEvents(_write_events(tmp_path / "e.h5"))
    with pytest.raises(ValueError, match="infections"):
        resolve_event_type(events, {"event_type": "typo"})


def test_output_path_uses_explicit_name_and_format():
    from ..animate_epidemic_example import resolve_output_path

    block = {"root": "out", "name": "plague_1348", "format": "mp4"}
    assert resolve_output_path(block, "infections") == "out/plague_1348.mp4"


def test_output_name_defaults_to_event_type_and_format_to_mp4():
    from ..animate_epidemic_example import resolve_output_path

    assert resolve_output_path({"root": "out"}, "infections") == "out/infections.mp4"


def test_load_config_reads_yaml_and_interpolates(tmp_path):
    from ..animate_epidemic_example import load_config

    config_file = tmp_path / "c.yaml"
    config_file.write_text(
        "data_root: /data\n"
        "inputs:\n"
        "  events: ${data_root}/e.h5\n"
    )
    config = load_config(config_file)
    assert config["inputs"]["events"] == "/data/e.h5"


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

    from ..animate_epidemic_example import located_events_for_map

    events = SimulationEvents(_write_events_with_seed_venue(tmp_path / "e.h5"))
    located = located_events_for_map(events, "infections")
    # venue 10 -> -1 -> person 1 -> 5 ; venue 11 -> 200 (unchanged).
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [5.0, 200.0])


def test_rate_metric_attributes_by_residence_not_venue():
    # A rate's denominator is resident population, so its numerator must count
    # residents; venue attribution puts a fair's visitors on its host unit and
    # yields impossible rates.
    from ..animate_epidemic_example import default_geo_priority

    assert default_geo_priority("rate_per_100k") == ("person",)


def test_count_metric_keeps_venue_attribution():
    # No denominator, so "where transmission happened" is the useful signal.
    from ..animate_epidemic_example import default_geo_priority

    assert default_geo_priority("count") == ("venue", "person")


def test_config_geo_priority_overrides_the_metric_default():
    from ..animate_epidemic_example import resolve_geo_priority

    # counts by residence — the configurable case
    assert resolve_geo_priority({"geo_priority": ["person"]}, "count") == ("person",)
    # a bare string is accepted alongside a list
    assert resolve_geo_priority({"geo_priority": "person"}, "count") == ("person",)


def test_absent_geo_priority_falls_back_to_metric_default():
    from ..animate_epidemic_example import resolve_geo_priority

    assert resolve_geo_priority({}, "rate_per_100k") == ("person",)
    assert resolve_geo_priority({}, "count") == ("venue", "person")


def test_unknown_geo_priority_source_is_rejected():
    from ..animate_epidemic_example import resolve_geo_priority

    with pytest.raises(ValueError, match="geo_priority.*postcode"):
        resolve_geo_priority({"geo_priority": ["postcode"]}, "count")


def test_person_priority_attributes_event_to_residence_not_venue(tmp_path):
    # person 2 lives in geo 6 but was infected at venue 11 in geo 200: under
    # person priority the event counts against 6, the unit whose population the
    # rate divides by.
    import numpy as np

    from core.load_data.simulation_events import SimulationEvents

    from ..animate_epidemic_example import located_events_for_map

    events = SimulationEvents(_write_events_with_seed_venue(tmp_path / "e.h5"))
    located = located_events_for_map(events, "infections", ("person",))
    np.testing.assert_array_equal(located["geo_unit_id"].to_numpy(), [5.0, 6.0])


def test_map_located_drops_geo_still_unplaceable(tmp_path):
    # -1 venue with no person source at all -> stays unresolved as NaN (aggregate
    # drops it), never a literal -1 the map cannot place.
    import h5py
    import numpy as np

    from core.load_data.simulation_events import SimulationEvents

    from ..animate_epidemic_example import located_events_for_map

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
