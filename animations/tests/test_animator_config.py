"""`animator_config.py`'s schema: interpolation, block construction/validation,
unknown-key rejection, geo_priority resolution, output-path assembly. No HDF5,
no render deps — the ordering-sensitive engine composition lives in
`build_pipeline` and is covered end-to-end in `test_build_pipeline.py`.
"""

from datetime import date

import pytest

from core.animations_core import RenderConfig

from ..animator_config import (
    AggregateConfig,
    AnimatorConfig,
    InputsConfig,
    OutputConfig,
    _construct,
    _render_config_from,
    default_geo_priority,
    resolve_geo_priority,
    resolve_interpolations,
)


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
    config = _render_config_from({"ramp": "inferno", "fps": 15})
    assert config.ramp == "inferno"
    assert config.fps == 15
    # untouched keys keep RenderConfig defaults
    assert config.metric == "rate_per_100k"
    assert config.sigma == 2.0


def test_empty_render_block_is_all_defaults():
    assert _render_config_from({}) == RenderConfig()
    assert _render_config_from(None) == RenderConfig()


def test_start_date_string_is_coerced_to_date():
    config = _render_config_from({"start_date": "1348-06-24"})
    assert config.start_date == date(1348, 6, 24)


def test_unknown_metric_is_rejected():
    with pytest.raises(ValueError, match="metric"):
        _render_config_from({"metric": "bananas"})


def test_unknown_render_key_raises_clean_error_not_a_traceback():
    # Was a raw TypeError before this module existed (mission consequence #4).
    with pytest.raises(ValueError, match="sigmaa"):
        _render_config_from({"sigmaa": 3})


def test_unknown_aggregate_key_is_rejected():
    # A typo'd `aggregate:` key used to be silently ignored (mission
    # consequence #3): `.get()` reads meant `window: 7` rendered a
    # perfectly-successful animation with no Trailing window and no message.
    with pytest.raises(ValueError, match="window"):
        _construct(AggregateConfig, {"window": 7}, "aggregate:")


def test_unknown_inputs_key_is_rejected():
    with pytest.raises(ValueError, match="typo"):
        _construct(InputsConfig, {"typo": "x"}, "inputs:")


def test_unknown_output_key_is_rejected():
    with pytest.raises(ValueError, match="typo"):
        _construct(OutputConfig, {"typo": "x"}, "output:")


def test_days_per_frame_default_is_a_single_source():
    # Two functions used to hardcode 1.0 independently (mission consequence
    # #1); now there's exactly one field with exactly one default.
    assert AggregateConfig().days_per_frame == 1.0


def test_window_days_coerced_and_multiple_of_days_per_frame_is_enforced():
    config = AggregateConfig(days_per_frame=1, window_days=7)
    assert config.days_per_frame == 1.0
    assert config.window_days == 7.0

    with pytest.raises(ValueError, match="window_days.*days_per_frame"):
        AggregateConfig(days_per_frame=2, window_days=7)


def test_rate_metric_attributes_by_residence_not_venue():
    # A rate's denominator is resident population, so its numerator must count
    # residents; venue attribution puts a fair's visitors on its host unit and
    # yields impossible rates.
    assert default_geo_priority("rate_per_100k") == ("person",)


def test_count_metric_keeps_venue_attribution():
    # No denominator, so "where transmission happened" is the useful signal.
    assert default_geo_priority("count") == ("venue", "person")


def test_config_geo_priority_overrides_the_metric_default():
    # counts by residence — the configurable case
    assert resolve_geo_priority({"geo_priority": ["person"]}, "count") == ("person",)
    # a bare string is accepted alongside a list
    assert resolve_geo_priority({"geo_priority": "person"}, "count") == ("person",)


def test_absent_geo_priority_falls_back_to_metric_default():
    assert resolve_geo_priority({}, "rate_per_100k") == ("person",)
    assert resolve_geo_priority({}, "count") == ("venue", "person")


def test_unknown_geo_priority_source_is_rejected():
    with pytest.raises(ValueError, match="geo_priority.*postcode"):
        resolve_geo_priority({"geo_priority": ["postcode"]}, "count")


def test_output_path_uses_explicit_name_and_format():
    config = AnimatorConfig(
        inputs=InputsConfig(),
        aggregate=AggregateConfig(event_type="infections"),
        render=RenderConfig(),
        output=OutputConfig(root="out", name="plague_1348", format="mp4"),
    )
    assert config.resolved_output_path == "out/plague_1348.mp4"


def test_output_name_defaults_to_event_type_and_format_to_mp4():
    config = AnimatorConfig(
        inputs=InputsConfig(),
        aggregate=AggregateConfig(event_type="infections"),
        render=RenderConfig(),
        output=OutputConfig(root="out"),
    )
    assert config.resolved_output_path == "out/infections.mp4"


def test_load_config_reads_yaml_and_interpolates(tmp_path):
    from ..animator_config import load_animator_config

    config_file = tmp_path / "c.yaml"
    config_file.write_text(
        "data_root: /data\n"
        "inputs:\n"
        "  events: ${data_root}/e.h5\n"
        "aggregate:\n"
        "  event_type: infections\n"
    )
    config = load_animator_config(config_file)
    assert config.inputs.events == "/data/e.h5"


def test_rate_per_100k_uses_person_geo_priority_by_default(tmp_path):
    # render: was resolved before geo_priority even in the old build_pipeline
    # ordering; here it's simply resolved eagerly at config-load time, which
    # this proves end to end through load_animator_config.
    from ..animator_config import load_animator_config

    config_file = tmp_path / "c.yaml"
    config_file.write_text(
        "inputs:\n"
        "  events: e.h5\n"
        "aggregate:\n"
        "  event_type: infections\n"
        "render:\n"
        "  metric: rate_per_100k\n"
    )
    config = load_animator_config(config_file)
    assert config.aggregate.geo_priority == ("person",)
